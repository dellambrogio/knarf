"""Text-to-speech: a worker thread that synthesizes queued text with Piper and plays it."""

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

from .config import BASE_LENGTH, PLAYER_LATENCY


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


def split_sentences(text):
    text = " ".join(text.split())
    parts = re.split(r"(?<=[.!?…])\s+", text)
    return [p for p in parts if p.strip()]
