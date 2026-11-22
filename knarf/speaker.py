"""Text-to-speech: Piper → ffmpeg compressor → normalized → pw-play, a sentence at a time.

Ported from hektor: the next sentence is made while the one before it plays, so the only gap is the
pause setting; the voice is evened out (compressor) and its peaks brought to the volume setting so it
carries on laptop speakers; markdown, links and URLs are never read out.
"""

import os
import queue
import re
import subprocess
import tempfile
import threading
import time
import wave

import numpy as np
from piper import PiperVoice, SynthesisConfig

from .config import BASE_LENGTH, PIPER_DIR, PLAYER_LATENCY, voices

# evens out loud and soft syllables so the voice carries on small speakers; then it's brought to full level
COMPRESS = "acompressor=threshold=-26dB:ratio=4:attack=4:release=80:makeup=2"
# the end of a sentence: . ! ? … (and closing quotes or brackets) before a space, or a line break
SENTENCE_END = re.compile(r"[.!?…][\"')\]]*(?=\s)|\n")
LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")  # [words](https://...): just the words
URL = re.compile(r"\(?\b(?:https?://|www\.)\S+")
MARKUP = re.compile(r"[*_#`>|]+")


def speakable(text: str) -> str:
    """What of `text` can be said aloud: no links or addresses, no markdown; "" if nothing's left."""
    text = MARKUP.sub("", URL.sub("", LINK.sub(r"\1", text)))
    text = " ".join(text.split()).strip(" -–—:;,")
    return text if any(c.isalnum() for c in text) else ""


def sentences(text: str) -> list[str]:
    """`text` in sentences, each one speakable. "3.5" stays one number."""
    out, start = [], 0
    text = text + "\n"
    for end in SENTENCE_END.finditer(text):
        if s := speakable(text[start:end.end()]):
            out.append(s)
        start = end.end()
    return out


class Speaker:
    """Background worker: speaks queued text, one utterance after another."""

    def __init__(self, settings):
        self.settings = settings
        self.voice_path = settings.voice_path()
        self.voice = PiperVoice.load(self.voice_path)
        self.extra_voices = {}  # voices asked for per text (say(voice=...)), loaded once
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
        # the first sentence shouldn't wait for piper and ffmpeg to warm up
        threading.Thread(target=lambda: self._make("Hello."), daemon=True).start()

    def say(self, text, done=None, voice=None, speed=None):
        """Queue `text`. `voice` (a voice file name, or part of it like "joe") and `speed` (percent) override
        the settings for this text only."""
        self.q.put((self.generation, text, done, (voice, speed)))

    def _voice_for(self, name):
        """The loaded voice for `name` ("en_US-joe-medium.onnx", "joe", ...), or None for the settings one."""
        if not name:
            return None
        match = next((v for v in voices() if v == name or name.lower() in v.lower()), None)
        if match is None:
            print(f"knarf: no voice matches {name!r}, using the settings one", flush=True)
            return None
        if match not in self.extra_voices:
            self.extra_voices[match] = PiperVoice.load(os.path.join(PIPER_DIR, match))
        return self.extra_voices[match]

    def stop(self):
        with self.lock:
            self.generation += 1
            p = self.proc
        while True:
            try:
                _, _, done, _ = self.q.get_nowait()
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
            gen, text, done, (voice, speed) = self.q.get()
            try:
                if gen == self.generation:
                    self.busy = True
                    self._speak(gen, text, voice, speed)
            except Exception as e:  # keep the worker alive no matter what
                print("knarf: speak failed:", e, flush=True)
            finally:
                with self.lock:
                    self.samples = None
                    self.caption = ""
                    self.busy = not self.q.empty()
                if done:
                    done.set()

    def _speak(self, gen, text, voice=None, speed=None):
        st = self.settings
        if st.voice_path() != self.voice_path:  # voice changed in settings
            self.voice_path = st.voice_path()
            self.voice = PiperVoice.load(self.voice_path)
        voice = self._voice_for(voice)
        ready = queue.Queue(maxsize=2)  # made sentences, waiting to be played

        def make():  # runs ahead of the playback, by up to two sentences
            for sentence in sentences(text):
                if gen != self.generation:
                    break
                ready.put((sentence, *self._make(sentence, voice, speed)))
            ready.put(None)

        threading.Thread(target=make, daemon=True).start()
        first = True
        while (item := ready.get()) is not None:
            if gen != self.generation:
                continue  # drain, so the maker isn't stuck on a full queue
            sentence, audio, rate = item
            if not first:
                time.sleep(st["pause"])
            first = False
            self._play(gen, audio, rate, sentence)

    def _make(self, sentence, voice=None, speed=None):
        """`sentence` as float32 samples, compressed and normalized, and its sample rate. `voice` (a loaded
        PiperVoice) and `speed` (percent) default to the settings."""
        st = self.settings
        voice = voice or self.voice
        cfg = SynthesisConfig(length_scale=BASE_LENGTH * 100 / max(10, speed or st["speed"]))
        pcm, rate = b"", voice.config.sample_rate
        for chunk in voice.synthesize(sentence, syn_config=cfg):
            pcm += chunk.audio_int16_bytes
            rate = chunk.sample_rate
        fmt = ["-f", "s16le", "-ar", str(rate), "-ac", "1"]
        done = subprocess.run(["ffmpeg", "-loglevel", "error", *fmt, "-i", "-", "-af", COMPRESS, *fmt, "-"],
                              input=pcm, capture_output=True)
        if done.returncode == 0 and done.stdout:
            pcm = done.stdout
        else:
            print("knarf: voice compressor failed, speaking without it", flush=True)
        audio = np.frombuffer(pcm, np.int16).astype(np.float32) / 32768
        peak = float(np.abs(audio).max()) if len(audio) else 0.0
        if peak:  # loudest peak at the volume setting
            audio = audio * (min(st["volume"], 100) / 100 * 0.97 / peak)
        return audio, rate

    def _play(self, gen, audio, rate, caption):
        pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()
        fd, path = tempfile.mkstemp(suffix=".wav", prefix="knarf-")
        os.close(fd)
        try:
            with wave.open(path, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(rate)
                w.writeframes(pcm)
            with self.lock:
                if gen != self.generation:
                    return
                self.proc = subprocess.Popen(
                    ["pw-play", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
                self.samples = audio
                self.rate = rate
                self.started = time.monotonic() + PLAYER_LATENCY
                self.caption = caption
            self.proc.wait()
        finally:
            os.unlink(path)
        with self.lock:
            self.samples = None
