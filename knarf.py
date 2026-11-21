#!/usr/bin/env python3
"""knarf — a little window that talks.

Runs a local HTTP endpoint; anything POSTed to /say is spoken with Piper
while the window animates along with the audio.

    POST http://127.0.0.1:47820/say      body = text   (?wait=1 to block until spoken)
    POST http://127.0.0.1:47820/stop     stop speaking and clear the queue
    GET  http://127.0.0.1:47820/status
"""

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
SPEED = float(os.environ.get("KNARF_SPEED", os.environ.get("SAY_SPEED", "1.3")))
SENTENCE_GAP = 0.35  # seconds of silence between sentences
PLAYER_LATENCY = 0.06  # rough pw-play startup latency, keeps visuals in sync

BG = "#000000"


class Speaker:
    """Background worker: synthesizes queued text and plays it sentence by sentence."""

    def __init__(self):
        self.voice = PiperVoice.load(MODEL)
        self.cfg = SynthesisConfig(length_scale=SPEED)
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
        for sentence in split_sentences(text):
            for chunk in self.voice.synthesize(sentence, syn_config=self.cfg):
                if gen != self.generation:
                    return
                self._play(gen, chunk, sentence)
                if gen != self.generation:
                    return
                time.sleep(SENTENCE_GAP)

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


def split_sentences(text):
    text = " ".join(text.split())
    parts = re.split(r"(?<=[.!?…])\s+", text)
    return [p for p in parts if p.strip()]


def make_server(speaker):
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
                self._reply(200, {"ok": True, "speaking": speaker.busy, "queued": speaker.pending()})
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
            elif u.path == "/stop":
                speaker.stop()
                self._reply(200, {"ok": True})
            else:
                self._reply(404, {"ok": False})

    return ThreadingHTTPServer((HOST, PORT), Handler)


def shade(rgb, k):
    return "#%02x%02x%02x" % tuple(int(max(0, min(255, v * k))) for v in rgb)


GREEN = (40, 255, 110)


class App:
    """Just a green circle on black that breathes when idle and swells with the voice."""

    def __init__(self, root, speaker):
        self.root = root
        self.sp = speaker
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
        self._tick()

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
        self._draw(time.monotonic() - self.t0)
        self.root.after(16, self._tick)

    def _draw(self, t):
        cv = self.cv
        cv.delete("all")
        w, h = cv.winfo_width(), cv.winfo_height()
        cx, cy = w / 2, h / 2
        lvl = self.level
        breathe = 0.5 + 0.5 * math.sin(t * 1.2)

        R = min(w, h) * 0.22 * (1 + 0.03 * breathe + 0.18 * lvl)
        bright = 0.45 + 0.1 * breathe * (1 - self.active) + 0.3 * self.active + 0.25 * lvl

        # soft halo
        spread = R * (0.5 + 0.5 * self.active + 0.6 * lvl)
        n = 28
        for i in range(n):
            k = i / n  # 0 = outermost
            r = R + spread * (1 - k)
            cv.create_oval(cx - r, cy - r, cx + r, cy + r, outline="",
                           fill=shade(GREEN, bright * 0.38 * k ** 2.2))

        # disc with a gentle radial gradient
        n = 18
        for i in range(n):
            k = i / n
            r = R * (1 - 0.55 * k)
            cv.create_oval(cx - r, cy - r, cx + r, cy + r, outline="",
                           fill=shade(GREEN, bright * (0.78 + 0.32 * k)))


def main():
    try:
        speaker = Speaker()
    except Exception as e:
        raise SystemExit(f"knarf: could not load voice {MODEL}: {e}")
    root = tk.Tk()
    App(root, speaker)
    try:
        server = make_server(speaker)
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


if __name__ == "__main__":
    main()
