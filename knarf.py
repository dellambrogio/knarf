#!/usr/bin/env python3
"""knarf — a little window that talks.

Runs a local HTTP endpoint; anything POSTed to /say is spoken with Piper
while the window animates along with the audio. It can also listen: on /listen
(or a click on the circle) it records until you go quiet, transcribes with
faster-whisper and types the text into the focused window with wtype.

    POST http://127.0.0.1:47820/say      body = text   (?wait=1 to block until spoken)
    POST http://127.0.0.1:47820/stop     stop speaking and clear the queue
    POST http://127.0.0.1:47820/listen   start listening (or stop, if already listening)
    POST http://127.0.0.1:47820/quit     close the window
    GET  http://127.0.0.1:47820/status
"""

import glob
import json
import math
import os
import queue
import re
import subprocess
import tempfile
import threading
import time
import tkinter as tk
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import numpy as np
from piper import PiperVoice, SynthesisConfig

PIPER_DIR = os.path.expanduser("~/.local/share/piper")
MODEL = os.environ.get("KNARF_MODEL", os.path.join(PIPER_DIR, "en_US-lessac-medium.onnx"))
HOST = "127.0.0.1"
PORT = int(os.environ.get("KNARF_PORT", "47820"))
BASE_LENGTH = float(os.environ.get("KNARF_SPEED", os.environ.get("SAY_SPEED", "1.3")))  # piper length scale at 100% speed
PLAYER_LATENCY = 0.06  # rough pw-play startup latency, keeps visuals in sync
CONFIG = os.path.expanduser("~/.config/knarf/settings.json")
QUIT = threading.Event()

BG = "#000000"
COLORS = {
    "green": (40, 255, 110),
    "cyan": (40, 220, 255),
    "amber": (255, 176, 0),
    "red": (255, 55, 40),
    "violet": (170, 95, 255),
    "white": (235, 235, 235),
}
DEFAULTS = {
    "speed": 100,      # percent
    "volume": 100,     # percent
    "pause": 0.35,     # seconds between sentences
    "voice": os.path.basename(MODEL),
    "color": "green",
    "size": 100,       # percent
    "on_top": False,
    "language": "en",     # whisper language code, or "auto" to detect
    "stt_model": "small", # whisper model size
    "silence": 1.2,       # seconds of silence that end a recording
    "send_enter": False,  # press Enter after typing the transcript
}
LANGUAGES = ["auto", "en", "it", "de", "fr", "es"]
STT_MODELS = ["tiny", "base", "small", "medium"]
MIC_RATE = 16000


def voices():
    return sorted(os.path.basename(p) for p in glob.glob(os.path.join(PIPER_DIR, "*.onnx")))


class Settings:
    """Small JSON-backed settings store in ~/.config/knarf/settings.json."""

    def __init__(self):
        self.data = dict(DEFAULTS)
        try:
            with open(CONFIG) as f:
                self.data.update({k: v for k, v in json.load(f).items() if k in DEFAULTS})
        except (OSError, ValueError):
            pass
        if self.data["color"] not in COLORS:
            self.data["color"] = DEFAULTS["color"]

    def __getitem__(self, k):
        return self.data[k]

    def set(self, k, v):
        self.data[k] = v
        self.save()

    def reset(self):
        self.data = dict(DEFAULTS)
        self.save()

    def save(self):
        os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
        tmp = CONFIG + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.data, f, indent=2)
        os.replace(tmp, CONFIG)

    def voice_path(self):
        p = os.path.join(PIPER_DIR, self.data["voice"])
        return p if os.path.exists(p) else MODEL


class Speaker:
    """Background worker: synthesizes queued text and plays it sentence by sentence."""

    def __init__(self, settings):
        self.settings = settings
        self.voice_path = settings.voice_path()
        self.voice = PiperVoice.load(self.voice_path)
        self.q = queue.Queue()
        self.lock = threading.Lock()
        self.generation = 0  # bumped on stop; stale work is dropped
        self.proc = None
        # state read by the UI
        self.samples = None  # float32 array of the sentence playing now
        self.rate = 22050
        self.started = 0.0
        self.caption = ""
        self.busy = False
        threading.Thread(target=self._run, daemon=True).start()

    def say(self, text, done=None):
        self.q.put((self.generation, text, done))

    def stop(self):
        with self.lock:
            self.generation += 1
            p = self.proc
        while True:
            try:
                _, _, done = self.q.get_nowait()
                if done:
                    done.set()
            except queue.Empty:
                break
        if p and p.poll() is None:
            p.terminate()

    def pending(self):
        return self.q.qsize()

    def _run(self):
        while True:
            gen, text, done = self.q.get()
            try:
                if gen == self.generation:
                    self.busy = True
                    self._speak(gen, text)
            except Exception as e:  # keep the worker alive no matter what
                print("knarf: speak failed:", e, flush=True)
            finally:
                with self.lock:
                    self.samples = None
                    self.caption = ""
                    self.busy = not self.q.empty()
                if done:
                    done.set()

    def _speak(self, gen, text):
        st = self.settings
        if st.voice_path() != self.voice_path:  # voice changed in settings
            self.voice_path = st.voice_path()
            self.voice = PiperVoice.load(self.voice_path)
        for sentence in split_sentences(text):
            cfg = SynthesisConfig(length_scale=BASE_LENGTH * 100 / max(10, st["speed"]),
                                  volume=st["volume"] / 100)
            for chunk in self.voice.synthesize(sentence, syn_config=cfg):
                if gen != self.generation:
                    return
                self._play(gen, chunk, sentence)
                if gen != self.generation:
                    return
                time.sleep(st["pause"])

    def _play(self, gen, chunk, caption):
        audio = np.asarray(chunk.audio_float_array, dtype=np.float32)
        pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()
        fd, path = tempfile.mkstemp(suffix=".wav", prefix="knarf-")
        os.close(fd)
        try:
            with wave.open(path, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(chunk.sample_rate)
                w.writeframes(pcm)
            with self.lock:
                if gen != self.generation:
                    return
                self.proc = subprocess.Popen(
                    ["pw-play", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
                self.samples = audio
                self.rate = chunk.sample_rate
                self.started = time.monotonic() + PLAYER_LATENCY
                self.caption = caption
            self.proc.wait()
        finally:
            os.unlink(path)
        with self.lock:
            self.samples = None


class Listener:
    """Records from the mic until silence, transcribes with faster-whisper, hands text to on_text."""

    FRAME = 480  # 30 ms at 16 kHz

    def __init__(self, settings, speaker, on_text):
        self.st, self.sp, self.on_text = settings, speaker, on_text
        self.state = "idle"  # idle | listening | thinking
        self.level = 0.0     # mic level 0..1 for the visuals
        self.stop_flag = False
        self.model, self.model_name = None, None
        self.model_lock = threading.Lock()
        threading.Thread(target=self._model, daemon=True).start()  # warm up in background

    def _model(self):
        with self.model_lock:
            name = self.st["stt_model"]
            if self.model is None or self.model_name != name:
                from faster_whisper import WhisperModel
                self.model = WhisperModel(name, device="cpu", compute_type="int8")
                self.model_name = name
            return self.model

    def toggle(self):
        if self.state == "listening":
            self.stop_flag = True
        elif self.state == "idle":
            self.state = "listening"
            self.stop_flag = False
            threading.Thread(target=self._session, daemon=True).start()

    def _session(self):
        try:
            self.sp.stop()  # don't record ourselves
            audio = self._record()
            if audio is None:
                return
            self.state = "thinking"
            lang = self.st["language"]
            segs, _ = self._model().transcribe(audio, beam_size=1, vad_filter=True,
                                               language=None if lang == "auto" else lang)
            text = " ".join(seg.text.strip() for seg in segs).strip()
            if text:
                self.on_text(text)
        except Exception as e:
            print("knarf: listen failed:", e, flush=True)
        finally:
            self.level = 0.0
            self.state = "idle"

    def _record(self):
        proc = subprocess.Popen(["arecord", "-q", "-f", "S16_LE", "-r", str(MIC_RATE), "-c", "1", "-t", "raw"],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        frames, floor = [], []
        started, quiet, n = False, 0, 0
        fsec = self.FRAME / MIC_RATE
        try:
            while not self.stop_flag:
                buf = proc.stdout.read(self.FRAME * 2)
                if len(buf) < self.FRAME * 2:
                    break
                x = np.frombuffer(buf, dtype="<i2").astype(np.float32) / 32768
                frames.append(x)
                n += 1
                rms = float(np.sqrt(np.mean(x ** 2)))
                self.level = min(1.0, rms * 12)
                if n <= 8:  # first ~0.25 s: measure the room
                    floor.append(rms)
                    continue
                thresh = max(0.012, 3.0 * float(np.median(floor)))
                if rms > thresh:
                    started, quiet = True, 0
                else:
                    quiet += 1
                if started and quiet * fsec >= self.st["silence"]:
                    break
                if not started and n * fsec > 8:  # nobody spoke
                    return None
                if n * fsec > 90:
                    break
        finally:
            proc.terminate()
            proc.wait()
        if not started:  # nothing but silence: don't let whisper invent text
            return None
        return np.concatenate(frames) if frames else None


def split_sentences(text):
    text = " ".join(text.split())
    parts = re.split(r"(?<=[.!?…])\s+", text)
    return [p for p in parts if p.strip()]


def make_server(speaker, listener):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _reply(self, code, obj):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if urlparse(self.path).path == "/status":
                self._reply(200, {"ok": True, "speaking": speaker.busy, "queued": speaker.pending(),
                                  "listening": listener.state})
            else:
                self._reply(404, {"ok": False})

        def do_POST(self):
            u = urlparse(self.path)
            n = int(self.headers.get("Content-Length") or 0)
            text = self.rfile.read(n).decode("utf-8", "replace").strip()
            if u.path == "/say":
                if not text:
                    return self._reply(400, {"ok": False, "error": "empty text"})
                wait = parse_qs(u.query).get("wait", ["0"])[0] not in ("0", "", "false")
                done = threading.Event() if wait else None
                speaker.say(text, done)
                if done:
                    done.wait()
                self._reply(200, {"ok": True})
            elif u.path == "/listen":
                listener.toggle()
                self._reply(200, {"ok": True, "listening": listener.state})
            elif u.path == "/stop":
                speaker.stop()
                self._reply(200, {"ok": True})
            elif u.path == "/quit":
                QUIT.set()
                self._reply(200, {"ok": True})
            else:
                self._reply(404, {"ok": False})

    return ThreadingHTTPServer((HOST, PORT), Handler)


def shade(rgb, k):
    return "#%02x%02x%02x" % tuple(int(max(0, min(255, v * k))) for v in rgb)


class App:
    """Just a circle on black that breathes when idle and swells with the voice."""

    def __init__(self, root, speaker, settings):
        self.root = root
        self.sp = speaker
        self.st = settings
        self.hover = False
        self.panel = None
        self.mic = 0.0
        self.inbox = queue.Queue()     # transcripts from the listener thread
        self.waiting_text = None       # transcript held until focus leaves knarf
        self.ls = Listener(settings, speaker, self.inbox.put)
        self.level = 0.0
        self.active = 0.0  # eases 0..1 as speech starts/stops
        self.t0 = time.monotonic()

        root.title("knarf")
        root.configure(bg=BG)
        root.geometry("420x420")
        root.minsize(160, 160)

        self.cv = tk.Canvas(root, bg=BG, highlightthickness=0)
        self.cv.pack(fill="both", expand=True)

        root.bind("<Escape>", lambda e: self.sp.stop())
        root.bind("<Control-q>", lambda e: root.destroy())
        root.bind("s", lambda e: self.open_settings())
        self.cv.bind("<Button-3>", lambda e: self.open_settings())
        self.cv.bind("<Enter>", lambda e: setattr(self, "hover", True))
        self.cv.bind("<Leave>", lambda e: setattr(self, "hover", False))
        self.cv.tag_bind("gear", "<Button-1>", lambda e: self.open_settings())
        self.cv.bind("<Button-1>", self._click)
        root.bind("<space>", lambda e: self.ls.toggle())
        root.bind("<FocusOut>", self._focus_out)
        root.attributes("-topmost", bool(self.st["on_top"]))
        self._tick()

    def _click(self, e):
        if "gear" not in self.cv.gettags("current"):
            self.ls.toggle()

    def _deliver(self, text):
        # Typing goes to the focused window. If that's knarf itself (you clicked the
        # circle), hold the text until you switch to another window.
        if self.root.focus_get() is not None:
            self.waiting_text = text
        else:
            self._type(text)

    def _focus_out(self, e):
        if e.widget is self.root and self.waiting_text:
            text, self.waiting_text = self.waiting_text, None
            self.root.after(250, lambda: self._type(text))

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

    def open_settings(self):
        if self.panel and self.panel.win.winfo_exists():
            self.panel.win.lift()
        else:
            self.panel = SettingsPanel(self)

    def _analyze(self):
        with self.sp.lock:
            s, rate, start = self.sp.samples, self.sp.rate, self.sp.started
        if s is None:
            return 0.0
        pos = int((time.monotonic() - start) * rate)
        if not 0 <= pos < len(s):
            return 0.0
        win = s[max(0, pos - 400): pos + 400]
        return min(1.0, float(np.sqrt(np.mean(win ** 2))) * 5.0) if len(win) else 0.0

    def _tick(self):
        lvl = self._analyze()
        # fast attack, slower release
        self.level += (lvl - self.level) * (0.5 if lvl > self.level else 0.12)
        self.active += ((1.0 if self.sp.busy else 0.0) - self.active) * 0.08
        self.mic += (self.ls.level - self.mic) * 0.35
        while not self.inbox.empty():
            self._deliver(self.inbox.get_nowait())
        if QUIT.is_set():
            self.root.destroy()
            return
        self._draw(time.monotonic() - self.t0)
        self.root.after(16, self._tick)

    def _draw(self, t):
        cv = self.cv
        cv.delete("all")
        w, h = cv.winfo_width(), cv.winfo_height()
        cx, cy = w / 2, h / 2
        lvl = self.level
        breathe = 0.5 + 0.5 * math.sin(t * 1.2)

        color = COLORS[self.st["color"]]
        R = min(w, h) * 0.22 * self.st["size"] / 100 * (1 + 0.03 * breathe + 0.18 * lvl + 0.12 * self.mic)
        bright = 0.45 + 0.1 * breathe * (1 - self.active) + 0.3 * self.active + 0.25 * lvl

        # soft halo
        spread = R * (0.5 + 0.5 * self.active + 0.6 * lvl)
        n = 28
        for i in range(n):
            k = i / n  # 0 = outermost
            r = R + spread * (1 - k)
            cv.create_oval(cx - r, cy - r, cx + r, cy + r, outline="",
                           fill=shade(color, bright * 0.38 * k ** 2.2))

        # disc with a gentle radial gradient
        n = 18
        for i in range(n):
            k = i / n
            r = R * (1 - 0.55 * k)
            cv.create_oval(cx - r, cy - r, cx + r, cy + r, outline="",
                           fill=shade(color, bright * (0.78 + 0.32 * k)))

        # listening: the circle becomes a ring that pulses with your voice;
        # thinking: a dim ring with a turning arc
        state = self.ls.state
        if state != "idle":
            r = R * (0.9 - 0.25 * self.mic if state == "listening" else 0.88)
            cv.create_oval(cx - R - 2, cy - R - 2, cx + R + 2, cy + R + 2, outline="", fill=BG)
            cv.create_oval(cx - R, cy - R, cx + R, cy + R, outline="",
                           fill=shade(color, 0.85 if state == "listening" else 0.3))
            cv.create_oval(cx - r, cy - r, cx + r, cy + r, outline="", fill=BG)
            if state == "thinking":
                m = (R + r) / 2
                cv.create_arc(cx - m, cy - m, cx + m, cy + m, start=-t * 300, extent=80,
                              style="arc", outline=shade(color, 1.0), width=max(2, R - r))

        if self.hover:  # settings gear, only while the mouse is over the window
            cv.create_text(w - 12, 10, text="⚙", anchor="ne", tags="gear",
                           fill=shade(color, 0.55), font=("Sans", 14))


class Slider(tk.Canvas):
    """Flat slider: thin track, filled part, round knob, value on the right."""

    W, PAD, VALW = 230, 8, 46

    def __init__(self, parent, value, lo, hi, step, fg, dim, on_change):
        super().__init__(parent, width=self.W, height=22, bg=BG, highlightthickness=0, cursor="hand2")
        self.lo, self.hi, self.step = lo, hi, step
        self.fg, self.dim, self.on_change = fg, dim, on_change
        self.value = value
        self.bind("<Button-1>", self._drag)
        self.bind("<B1-Motion>", self._drag)
        self.bind("<Button-4>", lambda e: self._nudge(1))
        self.bind("<Button-5>", lambda e: self._nudge(-1))
        self._draw()

    def _x(self, v):
        span = self.W - self.VALW - 2 * self.PAD
        return self.PAD + span * (v - self.lo) / (self.hi - self.lo)

    def _set(self, v):
        v = round(round((v - self.lo) / self.step) * self.step + self.lo, 4)
        v = max(self.lo, min(self.hi, v))
        if v != self.value:
            self.value = v
            self._draw()
            self.on_change(v)

    def _drag(self, e):
        span = self.W - self.VALW - 2 * self.PAD
        self._set(self.lo + (e.x - self.PAD) / span * (self.hi - self.lo))

    def _nudge(self, d):
        self._set(self.value + d * self.step)

    def _draw(self):
        self.delete("all")
        y, x0, x1, x = 11, self._x(self.lo), self._x(self.hi), self._x(self.value)
        self.create_line(x0, y, x1, y, fill=self.dim, width=3, capstyle="round")
        self.create_line(x0, y, x, y, fill=self.fg, width=3, capstyle="round")
        self.create_oval(x - 6, y - 6, x + 6, y + 6, fill=self.fg, outline="")
        txt = f"{self.value:g}" if self.step < 1 else f"{int(self.value)}"
        self.create_text(self.W - 2, y, text=txt, anchor="e", fill=self.fg, font=("Sans", 9))


class SettingsPanel:
    """Settings window; every change applies immediately and is saved."""

    def __init__(self, app):
        self.app = app
        st = app.st
        fg = shade(COLORS[st["color"]], 1.0)
        dim = shade(COLORS[st["color"]], 0.35)
        self.win = win = tk.Toplevel(app.root, bg=BG, padx=18, pady=14)
        win.title("knarf settings")
        win.resizable(False, False)
        win.bind("<Escape>", lambda e: win.destroy())
        font = ("Sans", 10)
        row = 0

        def label(text):
            tk.Label(win, text=text, bg=BG, fg=fg, font=font, anchor="w").grid(
                row=row, column=0, sticky="w", padx=(0, 14), pady=4)

        def slider(key, text, lo, hi, res, cast=int):
            nonlocal row
            label(text)
            Slider(win, st[key], lo, hi, res, fg, dim,
                   lambda v: st.set(key, cast(v))).grid(row=row, column=1, sticky="we", pady=4)
            row += 1

        slider("speed", "Speed %", 50, 200, 5)
        slider("volume", "Volume %", 0, 150, 5)
        slider("pause", "Pause between sentences (s)", 0, 1.5, 0.05, float)
        slider("size", "Circle size %", 40, 180, 5)

        label("Voice")
        vs = voices() or [st["voice"]]
        vvar = tk.StringVar(value=st["voice"] if st["voice"] in vs else vs[0])
        om = tk.OptionMenu(win, vvar, *vs, command=lambda v: st.set("voice", v))
        om.config(bg=BG, fg=fg, activebackground="#0c0c0c", activeforeground=fg,
                  highlightthickness=1, highlightbackground=dim, relief="flat", bd=0, font=font)
        om["menu"].config(bg=BG, fg=fg, activebackground=dim, activeforeground="#ffffff")
        om.grid(row=row, column=1, sticky="we", pady=4)
        row += 1

        def choice(key, text, options):
            nonlocal row
            label(text)
            var = tk.StringVar(value=st[key])
            m = tk.OptionMenu(win, var, *options, command=lambda v: st.set(key, v))
            m.config(bg=BG, fg=fg, activebackground="#0c0c0c", activeforeground=fg,
                     highlightthickness=1, highlightbackground=dim, relief="flat", bd=0, font=font)
            m["menu"].config(bg=BG, fg=fg, activebackground=dim, activeforeground="#ffffff")
            m.grid(row=row, column=1, sticky="we", pady=4)
            row += 1

        def check(key, text, apply=None):
            nonlocal row
            label(text)
            var = tk.BooleanVar(value=st[key])
            tk.Checkbutton(win, variable=var, bg=BG, fg=fg, selectcolor=BG, activebackground=BG,
                           activeforeground=fg, highlightthickness=0, bd=0,
                           command=lambda: (st.set(key, var.get()), apply and apply(var.get()))
                           ).grid(row=row, column=1, sticky="w")
            row += 1

        choice("language", "Listen: language", LANGUAGES)
        choice("stt_model", "Listen: model", STT_MODELS)
        slider("silence", "Listen: stop after silence (s)", 0.5, 3.0, 0.1, float)
        check("send_enter", "Listen: press Enter after typing")

        label("Colour")
        sw = tk.Canvas(win, bg=BG, highlightthickness=0, height=30, width=220)
        sw.grid(row=row, column=1, sticky="w", pady=4)
        for i, (name, rgb) in enumerate(COLORS.items()):
            x = 14 + i * 34
            if name == st["color"]:
                sw.create_oval(x - 13, 2, x + 13, 28, outline=shade(rgb, 1), width=2)
            sw.create_oval(x - 9, 6, x + 9, 24, fill=shade(rgb, 1), outline="", tags=name)
            sw.tag_bind(name, "<Button-1>", lambda e, n=name: self._color(n))
        row += 1

        check("on_top", "Always on top", lambda v: app.root.attributes("-topmost", v))

        bar = tk.Frame(win, bg=BG)
        bar.grid(row=row, column=0, columnspan=2, sticky="e", pady=(14, 0))
        btn = dict(bg=BG, fg=fg, activebackground="#0c0c0c", activeforeground=fg, relief="flat",
                   bd=0, padx=12, pady=5, highlightthickness=1, highlightbackground=dim, font=font)
        tk.Button(bar, text="Reset", command=self._reset, **btn).pack(side="left", padx=(0, 6))
        tk.Button(bar, text="Test voice", command=lambda: app.sp.say(
            "This is how I sound with these settings."), **btn).pack(side="left", padx=(0, 6))
        tk.Button(bar, text="Close", command=win.destroy, **btn).pack(side="left")

    def _reopen(self):
        self.win.destroy()
        self.app.panel = SettingsPanel(self.app)

    def _color(self, name):
        self.app.st.set("color", name)
        self._reopen()  # restyle the panel in the new colour

    def _reset(self):
        self.app.st.reset()
        self.app.root.attributes("-topmost", bool(self.app.st["on_top"]))
        self._reopen()


def main():
    settings = Settings()
    try:
        speaker = Speaker(settings)
    except Exception as e:
        raise SystemExit(f"knarf: could not load voice {settings.voice_path()}: {e}")
    root = tk.Tk(className="knarf")  # WM class, so sway can match the window
    app = App(root, speaker, settings)
    try:
        server = make_server(speaker, app.ls)
    except OSError:
        root.destroy()
        raise SystemExit(f"knarf: port {PORT} is busy — is knarf already running?")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"knarf listening on http://{HOST}:{PORT}", flush=True)
    try:
        root.mainloop()
    finally:
        speaker.stop()
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
