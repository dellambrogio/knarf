"""Speech-to-text: record from the mic until you go quiet, transcribe with faster-whisper.

How it tells talking from noise is hektor's: a 100 ms chunk only sounds like talking when it's loud
(over the background noise x NOISE_FACTOR) and voiced (vowels have a pitch; fans, hiss, key clicks
and thumps don't), and you're talking when SPEECH_RUN of the last few chunks do. The recording ends
after the silence setting without talking, where "quiet" is measured against your own speech
(SILENCE_SHARE of its typical level): the room is often louder while you talk than before.
"""

import bisect
import re
import threading
from collections import deque

import numpy as np

from .audio import CHUNK, CHUNK_S, HighPass, open_mic, rms, voicing
from .config import (MAX_LEN, MIC_HIGHPASS, MIN_RMS, NO_SPEECH, NOISE_FACTOR, SILENCE_SHARE, SPEECH_RUN,
                     VOICED)

# whisper tags noise as e.g. [BLANK_AUDIO], [Music], (wind blowing), alone or around the words
NOISE = re.compile(r"[\[(][^\])]*[\])]")


class Recorder:
    """Collects chunks until the speaker goes quiet: `add` returns None while recording, then True
    when something was said, False when nothing was.

    The first NOISE_CHUNKS measure the room (knarf only opens the mic when asked to listen, so there's
    no idle background measurement like hektor's); they're kept in the audio but never count as talking.
    """

    NOISE_CHUNKS = 3

    def __init__(self, silence_end: float) -> None:
        self.silence_end = silence_end
        self.frames: list[bytes] = []
        self.noise: list[float] = []
        self.threshold = float(MIN_RMS)
        self.heard, self.quiet, self.t = False, 0.0, 0.0
        self.recent: deque[bool] = deque(maxlen=SPEECH_RUN + 2)  # talking-like, last few chunks
        self.speech: list[float] = []  # levels of the talking-like chunks, sorted, once speech started
        self.first = self.last = 0     # chunks where talking started and was last heard

    @property
    def quiet_level(self) -> float:
        """Under this it's quiet: the threshold, or a share of the typical speech level if that's higher."""
        if not self.speech:
            return self.threshold
        return max(self.threshold, self.speech[len(self.speech) // 2] * SILENCE_SHARE)

    def add(self, data: bytes) -> bool | None:
        self.frames.append(data)
        self.t += CHUNK_S
        level = rms(data)
        if len(self.noise) < self.NOISE_CHUNKS:
            self.noise.append(level)
            # the quietest of them: you may already be talking in the others
            self.threshold = max(MIN_RMS, min(self.noise) * NOISE_FACTOR)
            return None
        talky = level > self.quiet_level and voicing(data) >= VOICED
        self.recent.append(talky)
        talking = sum(self.recent) >= SPEECH_RUN
        if talky and (self.heard or talking):
            bisect.insort(self.speech, level)
        if not self.heard and talking:
            self.heard = True
            self.first = len(self.frames) - len(self.recent)  # it started a few chunks back
        if talking:
            self.last = len(self.frames)
        if self.heard:
            self.quiet = 0.0 if talking else self.quiet + CHUNK_S
        if (self.heard and self.quiet >= self.silence_end) or self.t >= MAX_LEN:
            return self.heard
        if not self.heard and self.t >= NO_SPEECH:
            return False
        return None

    MARGIN = 3  # chunks kept before and after the talking

    def audio(self) -> np.ndarray:
        """The talking with a little margin, as float32 samples for whisper. The quiet before and after is
        left out: whisper makes up words ("You know.", "Thank you.") in silence."""
        frames = self.frames[max(0, self.first - self.MARGIN): self.last + self.MARGIN]
        return np.frombuffer(b"".join(frames), np.int16).astype(np.float32) / 32768


class Listener:
    """Listens on request (no wake word). Two ways to use it:

    - `toggle()`: dictation. Start (or stop early); the text goes to `on_text`, which types it.
    - `listen()`: for Claude (the MCP `listen` tool). Blocks and returns what was said.
    """

    def __init__(self, settings, speaker, on_text):
        self.st, self.sp, self.on_text = settings, speaker, on_text
        self.state = "idle"  # idle | listening | thinking
        self.level = 0.0     # mic level 0..1 for the visuals
        self.stop_flag = False
        self.lock = threading.Lock()
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
        else:
            self._start(self.on_text)

    def listen(self, timeout: float | None = None) -> str | None:
        """What the user said ("" if nothing), or None when already listening or transcribing."""
        box, done = {}, threading.Event()
        if not self._start(lambda text: box.update(text=text), done):
            return None
        done.wait(timeout)
        return box.get("text", "")

    def _start(self, deliver, done=None) -> bool:
        with self.lock:
            if self.state != "idle":
                return False
            self.state = "listening"
            self.stop_flag = False
        threading.Thread(target=self._session, args=(deliver, done), daemon=True).start()
        return True

    def _session(self, deliver, done):
        try:
            self.sp.stop()  # don't record ourselves
            audio = self._record()
            if audio is None:
                return
            self.state = "thinking"
            lang = self.st["language"]
            segs, _ = self._model().transcribe(audio, beam_size=1, vad_filter=True,
                                               condition_on_previous_text=False,
                                               language=None if lang == "auto" else lang)
            raw = " ".join(seg.text.strip() for seg in segs)
            text = " ".join(NOISE.sub("", raw).split())
            if not text:
                print(f"knarf: whisper heard no words{': ' + raw if raw.strip() else ''}", flush=True)
            elif deliver:
                deliver(text)
        except Exception as e:
            print("knarf: listen failed:", e, flush=True)
        finally:
            self.level = 0.0
            self.state = "idle"
            if done:
                done.set()

    def _record(self):
        proc, how = open_mic(self.st["noise_suppression"])
        print(f"knarf: listening on {how}", flush=True)
        highpass = HighPass(MIC_HIGHPASS) if MIC_HIGHPASS > 0 else None
        rec = Recorder(self.st["silence"])
        try:
            while not self.stop_flag:
                data = proc.stdout.read(CHUNK * 2)
                if len(data) < CHUNK * 2:
                    print("knarf: mic stream ended", flush=True)
                    break
                if highpass:
                    data = highpass(data)
                self.level = min(1.0, rms(data) / 2700)
                if rec.add(data) is not None:
                    break
        finally:
            proc.terminate()
            proc.wait()
        print(f"knarf: recorded {rec.t:.1f} s, noise {min(rec.noise or [0]):.0f}, threshold "
              f"{rec.threshold:.0f}, speech {'yes' if rec.heard else 'no'}", flush=True)
        # nothing but noise (or stopped before talking): don't let whisper invent text
        return rec.audio() if rec.heard else None
