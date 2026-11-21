"""Speech-to-text: record from the mic until silence, transcribe with faster-whisper."""

import subprocess
import threading

import numpy as np

from .config import MIC_RATE


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
