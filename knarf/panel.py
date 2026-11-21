"""The settings window: every change applies immediately and is saved."""

from .config import COLORS, LANGUAGES, STT_MODELS, voices
from .gtk import Gdk, GLib, Gtk
from .style import apply_css
from .sway import sway_center, sway_sticky


class SettingsPanel:
    """Settings window; every change applies immediately and is saved."""

    def __init__(self, circle):
        self.circle = circle
        st = circle.st
        self.win = win = Gtk.Window(title="knarf settings", resizable=False)
        win.add_css_class("knarf-settings")
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", lambda c, kv, kc, m: Gdk.keyval_name(kv) == "Escape" and (win.close() or True))
        win.add_controller(keys)

        grid = Gtk.Grid(row_spacing=8, column_spacing=16, margin_top=16, margin_bottom=14,
                        margin_start=18, margin_end=18)
        win.set_child(grid)
        row = 0

        def label(text):
            lb = Gtk.Label(label=text, xalign=0)
            grid.attach(lb, 0, row, 1, 1)

        def slider(key, text, lo, hi, step, cast=int):
            nonlocal row
            label(text)
            sc = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, step)
            sc.set_value(st[key])
            sc.set_digits(0 if step >= 1 else 2)
            sc.set_draw_value(True)
            sc.set_value_pos(Gtk.PositionType.RIGHT)
            sc.set_size_request(230, -1)
            sc.connect("value-changed",
                       lambda s: st.set(key, cast(round(round(s.get_value() / step) * step, 4))))
            grid.attach(sc, 1, row, 1, 1)
            row += 1

        def choice(key, text, options):
            nonlocal row
            label(text)
            dd = Gtk.DropDown.new_from_strings(options)
            dd.set_selected(options.index(st[key]) if st[key] in options else 0)
            dd.connect("notify::selected", lambda d, _p: st.set(key, options[d.get_selected()]))
            grid.attach(dd, 1, row, 1, 1)
            row += 1

        def check(key, text, apply=None):
            nonlocal row
            label(text)
            cb = Gtk.CheckButton(active=bool(st[key]))
            cb.connect("toggled", lambda c: (st.set(key, c.get_active()), apply and apply(c.get_active())))
            grid.attach(cb, 1, row, 1, 1)
            row += 1

        slider("speed", "Speed %", 50, 200, 5)
        slider("volume", "Volume %", 0, 150, 5)
        slider("pause", "Pause between sentences (s)", 0, 1.5, 0.05, float)
        slider("size", "Circle size %", 40, 180, 5)
        choice("voice", "Voice", voices() or [st["voice"]])
        choice("language", "Listen: language", LANGUAGES)
        choice("stt_model", "Listen: model", STT_MODELS)
        slider("silence", "Listen: stop after silence (s)", 0.5, 3.0, 0.1, float)
        check("send_enter", "Listen: press Enter after typing")

        label("Colour")
        box = Gtk.Box(spacing=8)
        self.swatches = {}
        for name in COLORS:
            b = Gtk.Button()
            b.add_css_class("swatch")
            b.add_css_class(f"swatch-{name}")
            b.set_tooltip_text(name)
            b.connect("clicked", lambda _b, n=name: self._color(n))
            box.append(b)
            self.swatches[name] = b
        grid.attach(box, 1, row, 1, 1)
        row += 1
        self._mark(st["color"])

        check("popup", "Pop up while speaking or listening")
        check("sticky", "Show on all workspaces", sway_sticky)

        bar = Gtk.Box(spacing=6, halign=Gtk.Align.END, margin_top=10)
        for text, fn in (("Reset", self._reset),
                         ("Test voice", lambda: circle.sp.say("This is how I sound with these settings.")),
                         ("Close", win.close)):
            b = Gtk.Button(label=text)
            b.connect("clicked", lambda _b, f=fn: f())
            bar.append(b)
        grid.attach(bar, 0, row, 2, 1)
        win.present()
        # The circle's sway rule (app_id knarf) also matches this window and would put it in the
        # corner at the circle's size: put it back at its natural size, in the middle of the screen.
        GLib.timeout_add(100, self._center)

    def _center(self):
        grid = self.win.get_child()
        w = grid.measure(Gtk.Orientation.HORIZONTAL, -1)[1]
        h = grid.measure(Gtk.Orientation.VERTICAL, w)[1]
        sway_center(self.win.get_title(), w, h)
        return False

    def _mark(self, name):
        for n, b in self.swatches.items():
            (b.add_css_class if n == name else b.remove_css_class)("selected")

    def _color(self, name):
        self.circle.st.set("color", name)
        apply_css(name)
        self._mark(name)
        self.circle.tray.refresh()

    def _reset(self):
        self.circle.st.reset()
        apply_css(self.circle.st["color"])
        sway_sticky(bool(self.circle.st["sticky"]))
        self.win.close()
        self.circle.panel = SettingsPanel(self.circle)
