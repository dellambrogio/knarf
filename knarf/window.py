"""The circle window: transparent and borderless, only the circle shows."""

import math
import os
import subprocess
import sys
import threading
import time
import types

import numpy as np

from .config import COLORS
from .gtk import Gdk, GLib, Gtk, cairo
from .panel import SettingsPanel
from .server import COMMANDS, QUIT, WINDOW_VISIBLE
from .style import apply_css
from . import wm
from .tray import Tray


class Circle:
    """A borderless, transparent window: only the circle shows. It breathes when idle,
    swells with the voice, and turns into a ring while listening."""

    @classmethod
    def offscreen(cls, settings, state="idle", level=0.0, active=0.0, mic=0.0, t=0.0):
        """A Circle with no window, for drawing frames with `_draw` (docs screenshots, the demo video).
        Set level, active, mic, ls.state and t0 on it between frames."""
        c = cls.__new__(cls)
        c.st = settings
        c.level, c.active, c.mic = level, active, mic
        c.t0 = time.monotonic() - t
        c.ls = types.SimpleNamespace(state=state)
        c.sp = types.SimpleNamespace(lock=threading.Lock(), caption="")  # captions are drawn by the caller
        c.caption, c.caption_until = "", 0.0
        return c

    def __init__(self, gapp, speaker, listener, inbox, settings):
        self.gapp, self.sp, self.ls, self.inbox, self.st = gapp, speaker, listener, inbox, settings
        self.level = 0.0
        self.active = 0.0  # eases 0..1 as speech starts/stops
        self.mic = 0.0
        self.t0 = time.monotonic()
        self.panel = None
        self.waiting_text = None  # transcript held until focus leaves knarf
        self.wm = wm.detect()     # placing, focus, sticky: asked of the window manager
        self.auto_shown = False   # the circle popped up by itself and should hide again
        self.idle_since = None
        self.caption, self.caption_until = "", 0.0  # what's shown under the circle, and until when
        gapp.hold()  # keep running while the window is hidden

        apply_css(self.st["color"])
        self.win = win = Gtk.ApplicationWindow(application=gapp, title="knarf")
        win.set_decorated(False)
        win.set_default_size(360, 360)
        win.add_css_class("knarf-main")
        self.area = Gtk.DrawingArea()
        self.area.set_draw_func(self._draw)
        win.set_child(self.area)

        click = Gtk.GestureClick(button=0)
        click.connect("pressed", self._pressed)
        self.area.add_controller(click)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._key)
        win.add_controller(keys)
        win.connect("notify::is-active", self._active_changed)
        win.connect("close-request", lambda w: (self.hide_window(), True)[1])  # close = hide
        self.area.add_tick_callback(self._tick)
        self.tray = Tray(self)
        GLib.timeout_add(50, self._control)  # runs even while the window is hidden

    # --- showing and hiding ------------------------------------------------------
    def show_window(self, auto=False):
        self.auto_shown = auto
        if self.win.get_visible():
            return
        # Popping up shouldn't steal the keyboard from what you're doing: hand focus back.
        prev = self.wm.focused_window() if auto else None
        self.win.present()
        WINDOW_VISIBLE.set()
        GLib.timeout_add(100, lambda: self.place() and False)
        if prev is not None:
            GLib.timeout_add(150, lambda: self.wm.focus_window(prev) and False)
        if self.st["sticky"]:
            GLib.timeout_add(200, lambda: self.wm.set_sticky(True) and False)

    def place(self):
        """Put the circle where the settings say (on the screen you're on)."""
        self.wm.place_window(self.st["position"], self.win.get_width() or 360, self.win.get_height() or 360)

    def hide_window(self):
        self.auto_shown = False
        self.win.set_visible(False)
        WINDOW_VISIBLE.clear()

    def toggle_window(self):
        if self.win.get_visible() and not self.auto_shown:
            self.hide_window()
        else:
            self.show_window()

    def restart(self):
        if os.environ.get("INVOCATION_ID"):  # running as the systemd service: let systemd do it
            subprocess.Popen(["systemctl", "--user", "restart", "knarf.service"])
        else:  # started by hand: replace this process with a fresh one (sockets close on exec)
            self.sp.stop()
            os.execv(sys.executable, [sys.executable] + sys.argv)

    def _control(self):
        if QUIT.is_set():
            self.gapp.quit()
            return GLib.SOURCE_REMOVE
        while not COMMANDS.empty():
            {"toggle": self.toggle_window, "show": self.show_window, "hide": self.hide_window}[COMMANDS.get_nowait()]()
        while not self.inbox.empty():
            self._deliver(self.inbox.get_nowait())
        state = self.ls.state if self.ls.state != "idle" else ("speaking" if self.sp.busy else "idle")
        self.tray.set_state(state)
        if state != "idle":
            self.idle_since = None
            if self.st["popup"] and not self.win.get_visible():
                self.show_window(auto=True)
        elif self.auto_shown:
            now = time.monotonic()
            self.idle_since = self.idle_since or now
            if now - self.idle_since > max(1.5, self.st["caption_hold"]):
                self.hide_window()
        return GLib.SOURCE_CONTINUE

    # --- input ---------------------------------------------------------------
    def _pressed(self, gesture, n, x, y):
        b = gesture.get_current_button()
        if b == 1:
            self.ls.toggle()
        elif b == 2:
            self.sp.stop()
        elif b == 3:
            self.open_settings()

    def _key(self, ctrl, keyval, keycode, mods):
        name = Gdk.keyval_name(keyval)
        if name == "Escape":
            self.sp.stop()
        elif name == "space":
            self.ls.toggle()
        elif name in ("s", "S"):
            self.open_settings()
        elif name == "q" and mods & Gdk.ModifierType.CONTROL_MASK:
            self.hide_window()
        else:
            return False
        return True

    def open_settings(self):
        if self.panel and self.panel.win.get_visible():
            self.panel.win.present()
        else:
            self.panel = SettingsPanel(self)

    # --- transcripts -----------------------------------------------------------
    def _deliver(self, text):
        # Typing goes to the focused window. If that's knarf itself (you clicked the
        # circle), hold the text until you switch to another window.
        if self.win.is_active():
            self.waiting_text = text
        else:
            self._type(text)

    def _active_changed(self, win, _pspec):
        if not win.is_active() and self.waiting_text:
            text, self.waiting_text = self.waiting_text, None
            GLib.timeout_add(250, lambda: self._type(text) and False)

    def _type(self, text):
        enter = self.st["send_enter"]

        def run():
            try:
                subprocess.run(["wtype", "--", text], check=True)
                if enter:
                    subprocess.run(["wtype", "-k", "Return"], check=True)
            except (OSError, subprocess.CalledProcessError) as e:
                print("knarf: typing failed:", e, flush=True)

        threading.Thread(target=run, daemon=True).start()

    # --- animation ---------------------------------------------------------------
    def _analyze(self):
        with self.sp.lock:
            s, rate, start = self.sp.samples, self.sp.rate, self.sp.started
        if s is None:
            return 0.0
        pos = int((time.monotonic() - start) * rate)
        if not 0 <= pos < len(s):
            return 0.0
        win = s[max(0, pos - 400): pos + 400]
        return min(1.0, float(np.sqrt(np.mean(win ** 2))) * 3.0) if len(win) else 0.0

    def _tick(self, widget, clock):  # animation only; runs while the window is visible
        lvl = self._analyze()
        # fast attack, slower release
        self.level += (lvl - self.level) * (0.5 if lvl > self.level else 0.12)
        self.active += ((1.0 if self.sp.busy else 0.0) - self.active) * 0.08
        self.mic += (self.ls.level - self.mic) * 0.35
        widget.queue_draw()
        return GLib.SOURCE_CONTINUE

    def _draw(self, area, cr, w, h):
        cr.set_operator(cairo.OPERATOR_CLEAR)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)

        t = time.monotonic() - self.t0
        rgb = [c / 255 for c in COLORS[self.st["color"]]]
        R0 = min(w, h) * 0.2 * self.st["size"] / 100  # the circle's resting radius; the bars fit in it too
        (self._draw_bars if self.st["style"] == "bars" else self._draw_circle)(cr, w, h, t, rgb, R0)

        with self.sp.lock:
            said = self.sp.caption
        now = time.monotonic()
        if said:  # keep the last sentence a while after the voice stops
            self.caption, self.caption_until = said, now + self.st["caption_hold"]
        elif now > self.caption_until:
            self.caption = ""
        if self.caption:
            # below the circle at its loudest, so the text doesn't bounce with the voice
            self._caption(cr, self.caption, w, h / 2 + R0 * 1.35 + 16, h - 6, rgb)

    def _draw_bars(self, cr, w, h, t, rgb, R0):
        """Three columns of light segments, lit from the middle outwards as the voice gets
        louder, the middle column the most. Dim and still when idle; the mic level lights them while
        listening, and a light runs up and down while thinking."""
        cx, cy = w / 2, h / 2
        state = self.ls.state
        n = 15                                   # segments per column (odd: one sits on the middle line)
        H = R0 * 2.3                             # the columns' height
        seg = H / n
        cw = R0 * 0.36                           # a column's width
        gap = cw * 0.45

        if state == "listening":
            amount, k = self.mic, 0.7
        elif state == "thinking":
            amount, k = 0.0, 0.7
        else:
            amount, k = self.level, 1.0
        half = n // 2
        scan = (math.sin(t * 4) * 0.5 + 0.5) * (n - 1)  # thinking: a light running up and down
        for c, share in ((-1, 0.65), (0, 1.0), (1, 0.65)):  # the side columns light up less
            x = cx + c * (cw + gap) - cw / 2
            lit = amount * share * (half + 1)  # segments lit on each side of the middle
            for i in range(n):
                d = abs(i - half)  # distance from the middle line
                on = max(0.0, min(1.0, lit - d))  # partly lit at the edge, so it moves smoothly
                if state == "thinking" and c == 0:
                    on = max(0.0, 1 - abs(i - scan))
                b = 0.12 + 0.88 * on * k
                cr.set_source_rgba(*[min(1.0, v * b) for v in rgb], 1)
                cr.rectangle(x, cy - H / 2 + i * seg + seg * 0.12, cw, seg * 0.76)
                cr.fill()

    def _draw_circle(self, cr, w, h, t, rgb, R0):
        cx, cy = w / 2, h / 2
        lvl = self.level
        breathe = 0.5 + 0.5 * math.sin(t * 1.2)
        # leave room for the glow inside the window
        R = R0 * (1 + 0.03 * breathe + 0.18 * lvl + 0.12 * self.mic)
        bright = 0.45 + 0.1 * breathe * (1 - self.active) + 0.3 * self.active + 0.25 * lvl
        state = self.ls.state

        def col(k):
            return [min(1.0, c * k) for c in rgb]

        # soft glow: the same green fading to fully transparent
        # the glow must fade out before the window edge, or it shows as a square
        outer = min(R + R * (0.45 + 0.35 * self.active + 0.5 * lvl + 0.3 * self.mic), min(w, h) / 2 - 1)
        inner = R * 0.9
        g = cairo.RadialGradient(cx, cy, inner, cx, cy, outer)
        for i in range(9):
            k = i / 8
            g.add_color_stop_rgba(k, *col(1.0), min(1.0, bright * 0.75) * (1 - k) ** 2.2)
        cr.set_source(g)
        cr.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)  # a ring: keep the middle see-through
        cr.arc(cx, cy, outer, 0, 2 * math.pi)
        cr.new_sub_path()
        cr.arc(cx, cy, inner, 0, 2 * math.pi)
        cr.fill()
        cr.set_fill_rule(cairo.FILL_RULE_WINDING)

        if state == "idle":
            # the disc, a touch brighter in the middle
            g = cairo.RadialGradient(cx, cy, 0, cx, cy, R)
            g.add_color_stop_rgba(0.0, *col(bright * 1.1), 1)
            g.add_color_stop_rgba(0.45, *col(bright * 1.0), 1)
            g.add_color_stop_rgba(1.0, *col(bright * 0.8), 1)
            cr.set_source(g)
            cr.arc(cx, cy, R, 0, 2 * math.pi)
            cr.fill()
        else:
            # listening: a ring that thickens with your voice; thinking: dim ring + turning arc
            r = R * (0.9 - 0.25 * self.mic if state == "listening" else 0.88)
            cr.set_line_width(R - r)
            cr.set_source_rgba(*col(0.85 if state == "listening" else 0.3), 1)
            cr.arc(cx, cy, (R + r) / 2, 0, 2 * math.pi)
            cr.stroke()
            if state == "thinking":
                a = t * 5.2
                cr.set_source_rgba(*col(1.0), 1)
                cr.arc(cx, cy, (R + r) / 2, a, a + 1.4)
                cr.stroke()


    def _caption(self, cr, text, w, top, bottom, rgb):
        """The sentence being said, wrapped and centred under the circle, on a dark backing."""
        cr.select_font_face("monospace")
        cr.set_font_size(13)
        ext = cr.font_extents()
        lh = ext[2] + 2  # line height
        lines, line = [], ""
        for word in text.split():
            if line and cr.text_extents(line + " " + word).x_advance > w - 36:
                lines.append(line)
                line = word
            else:
                line = (line + " " + word).strip()
        lines.append(line)
        fit = max(1, int((bottom - top) // lh))
        if len(lines) > fit:  # too long for the space: keep the start, mark the cut
            lines = lines[:fit]
            lines[-1] += " …"
        width = max(cr.text_extents(ln).x_advance for ln in lines)
        x0, y0 = (w - width) / 2 - 8, top - ext[0] - 4
        cr.set_source_rgba(0, 0, 0, 0.7)
        cr.rectangle(x0, y0, width + 16, len(lines) * lh + 8)
        cr.fill()
        cr.set_source_rgba(*rgb, 1)
        for i, ln in enumerate(lines):
            cr.move_to((w - cr.text_extents(ln).x_advance) / 2, top + i * lh)
            cr.show_text(ln)
