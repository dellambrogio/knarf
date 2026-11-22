#!/usr/bin/env python3
"""Make docs/demo.mp4: knarf speaking, listening to you, transcribing and answering, with sound.

Rendered offline, frame by frame, with the real voice (Speaker._make: Piper + compressor) and the real
drawing code (Circle._draw), so nothing on the desktop shows. "You" are the same voice pitched down.
Run with `just demo`.
"""

import math
import subprocess
import sys
import time
import types
import wave
from pathlib import Path

import numpy as np
from piper import PiperVoice

from knarf.config import Settings
from knarf.gtk import cairo
from knarf.speaker import Speaker, sentences
from knarf.window import Circle

SIZE, FPS = 480, 30
CAPTION_H = 70

# (kind, text or seconds): what happens, in order
SCRIPT = [
    ("idle", 1.2),
    ("knarf", "Hi, I'm knarf. I give Claude Code a voice, and ears."),
    ("idle", 0.6),
    ("you", "Can you check the build and tell me if the tests pass?"),
    ("thinking", 1.4),
    ("knarf", "Sure. The build is green, and all forty two tests pass."),
    ("idle", 1.5),
]


def make_track(st):
    """The sound, and per sample what's going on: (audio, rate, segments of (start, end, kind, text))."""
    voice = PiperVoice.load(st.voice_path())
    maker = types.SimpleNamespace(voice=voice, settings=st)
    rate = voice.config.sample_rate
    parts, segments, t = [], [], 0.0

    def add(audio, kind, text=""):
        nonlocal t
        parts.append(audio.astype(np.float32))
        segments.append((t, t + len(audio) / rate, kind, text))
        t += len(audio) / rate

    for kind, what in SCRIPT:
        if kind in ("idle", "thinking"):
            add(np.zeros(int(what * rate)), kind)
        elif kind == "knarf":
            for i, s in enumerate(sentences(what)):
                if i:
                    add(np.zeros(int(st["pause"] * rate)), "knarf-pause", what)
                audio, _ = Speaker._make(maker, s)
                add(audio, "knarf", what)
        elif kind == "you":
            add(np.zeros(int(0.5 * rate)), "listening", what)  # the ring opens, you start a moment later
            audio, _ = Speaker._make(maker, what)
            add(you_voice(audio, rate) * 0.8, "listening", what)
            add(np.zeros(int(1.2 * rate)), "listening", what)  # quiet until it stops recording
    return np.concatenate(parts), rate, segments


def you_voice(audio, rate):
    """The same voice, deeper and a bit slower: someone else."""
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()
    fmt = ["-f", "s16le", "-ar", str(rate), "-ac", "1"]
    out = subprocess.run(["ffmpeg", "-loglevel", "error", *fmt, "-i", "-",
                          "-af", f"asetrate={rate}*0.82,aresample={rate},atempo=1.1", *fmt, "-"],
                         input=pcm, capture_output=True, check=True).stdout
    return np.frombuffer(out, np.int16).astype(np.float32) / 32768


def level(audio, rate, t, scale):
    i = int(t * rate)
    win = audio[max(0, i - 400): i + 400]
    return min(1.0, float(np.sqrt(np.mean(win ** 2))) * scale) if len(win) else 0.0


def caption(cr, text, who, w, y):
    if not text:
        return
    cr.select_font_face("monospace")
    cr.set_font_size(15)
    line, lines = "", []
    for word in f"{who}: {text}".split():  # wrap to the width
        if cr.text_extents(line + " " + word).width > w - 40 and line:
            lines.append(line)
            line = word
        else:
            line = (line + " " + word).strip()
    lines.append(line)
    cr.set_source_rgb(0.2, 1.0, 0.4) if who == "knarf" else cr.set_source_rgb(0.75, 0.9, 0.78)
    for i, ln in enumerate(lines):
        cr.move_to((w - cr.text_extents(ln).width) / 2, y + i * 20)
        cr.show_text(ln)


def main(out):
    st = Settings()
    audio, rate, segments = make_track(st)
    duration = len(audio) / rate
    wav = Path(out).with_suffix(".wav")
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes())

    W, H = SIZE, SIZE + CAPTION_H  # even sizes, for yuv420p
    ff = subprocess.Popen(
        ["ffmpeg", "-loglevel", "error", "-y",
         "-f", "rawvideo", "-pix_fmt", "bgra", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
         "-i", str(wav), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20",
         "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", out],
        stdin=subprocess.PIPE)
    fake = Circle.offscreen(dict(st.data, style="circle"))
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
    k = 60 / FPS  # the app smooths at 60 fps
    for n in range(int(math.ceil(duration * FPS))):
        t = n / FPS
        kind, text = next(((s[2], s[3]) for s in segments if s[0] <= t < s[1]), ("idle", ""))
        speaking = kind.startswith("knarf")
        state = {"listening": "listening", "thinking": "thinking"}.get(kind, "idle")
        voice = level(audio, rate, t, 3.0) if kind == "knarf" else 0.0
        mic = level(audio, rate, t, 12.0) if kind == "listening" else 0.0
        a = 0.5 if voice > fake.level else 0.12  # same easing as Circle._tick, per frame at 30 fps
        fake.level += (voice - fake.level) * min(1, a * k)
        fake.active += ((1.0 if speaking else 0.0) - fake.active) * min(1, 0.08 * k)
        fake.mic += (mic - fake.mic) * min(1, 0.35 * k)
        fake.ls.state = state
        fake.t0 = time.monotonic() - t

        cr = cairo.Context(surf)
        cr.set_source_rgb(0, 0, 0)
        cr.paint()
        cr.save()
        cr.rectangle(0, 0, SIZE, SIZE)
        cr.clip()
        Circle._draw(fake, None, cr, SIZE, SIZE)
        cr.restore()
        if kind.startswith("knarf"):
            caption(cr, text, "knarf", W, SIZE + 10)
        elif kind == "listening":
            caption(cr, text, "you", W, SIZE + 10)
        elif kind == "thinking":
            caption(cr, "transcribing...", "knarf", W, SIZE + 10)
        surf.flush()
        ff.stdin.write(bytes(surf.get_data()))
    ff.stdin.close()
    ff.wait()
    wav.unlink()
    print(f"wrote {out} ({duration:.1f} s)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).resolve().parent.parent / "docs" / "demo.mp4"))
