"""Mic basics, ported from hektor: telling talking from noise, a high-pass filter, picking the mic.

Levels are RMS in 16-bit sample units (0-32767), like hektor's, so its tuning carries over.
"""

import array
import json
import math
import subprocess

import numpy as np

RATE = 16000
CHUNK = RATE // 10  # 100 ms, as samples
CHUNK_S = 0.1

# `just audio-setup`: PipeWire's WebRTC noise suppression as an extra "knarf mic" (pipewire/knarf-echo-cancel.conf)
EC_MIC, EC_CAPTURE = "knarf_mic", "knarf_ec_capture"


def rms(data: bytes) -> float:
    x = np.frombuffer(data, np.int16).astype(np.float32)
    return float(np.sqrt(np.mean(x * x))) if len(x) else 0.0


VOICE_FRAME = 512  # samples, 32 ms: long enough for two periods of a low voice


def voicing(data: bytes) -> float:
    """How voiced a chunk is, 0-1: the strongest pitch-like repetition (70-400 Hz) in any of three short
    frames in it. Vowels give ~0.6-1; hiss, fans, key clicks and thumps ~0.2-0.45."""
    x = np.frombuffer(data, np.int16).astype(np.float32)
    lags = np.arange(RATE // 400, RATE // 70)
    best = 0.0
    for start in range(0, len(x) - VOICE_FRAME + 1, max(1, (len(x) - VOICE_FRAME) // 2)):
        f = x[start:start + VOICE_FRAME]
        f = f - f.mean()
        spec = np.fft.rfft(f, 2 * VOICE_FRAME)
        ac = np.fft.irfft(spec * np.conj(spec))[:VOICE_FRAME]
        if ac[0] > 0:  # normalized by how much of the frame overlaps at each lag
            best = max(best, float((ac[lags] / (ac[0] * (VOICE_FRAME - lags) / VOICE_FRAME)).max()))
    return min(best, 1.0)


class HighPass:
    """Cuts hum and rumble below `cutoff` Hz: two 2nd-order Butterworth sections, kept across chunks."""

    def __init__(self, cutoff: float) -> None:
        w0 = 2 * math.pi * cutoff / RATE
        alpha, cos = math.sin(w0) / (2 * 0.7071), math.cos(w0)
        a0 = 1 + alpha
        self.b = ((1 + cos) / 2 / a0, -(1 + cos) / a0, (1 + cos) / 2 / a0)
        self.a = (-2 * cos / a0, (1 - alpha) / a0)
        self.state = [[0.0] * 4, [0.0] * 4]  # x1, x2, y1, y2 per section

    def __call__(self, data: bytes) -> bytes:
        out = [float(s) for s in array.array("h", data)]
        (b0, b1, b2), (a1, a2) = self.b, self.a
        for st in self.state:
            x1, x2, y1, y2 = st
            for i, x in enumerate(out):
                y = b0 * x + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
                x2, x1, y2, y1 = x1, x, y1, y
                out[i] = y
            st[:] = x1, x2, y1, y2
        return array.array("h", (max(-32768, min(32767, round(y))) for y in out)).tobytes()


def pw_dump() -> list:
    try:
        return json.loads(subprocess.run(["pw-dump"], capture_output=True, text=True, timeout=3).stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []


def pw_node(name: str, objs: list | None = None) -> int | None:
    """Id of the PipeWire node called `name`, None if there's none."""
    return next((o["id"] for o in (pw_dump() if objs is None else objs)
                 if o.get("type") == "PipeWire:Interface:Node"
                 and o.get("info", {}).get("props", {}).get("node.name") == name), None)


def pick_mic(objs: list) -> str | None:
    """Pick the microphone: any USB mic, the default input if it's a real microphone, else the built-in one.

    Bluetooth earbuds in music mode (A2DP) become the default "source" but have no mic, which records
    pure silence.
    """
    sources = [o["info"]["props"] for o in objs
               if o.get("type") == "PipeWire:Interface:Node"
               and o.get("info", {}).get("props", {}).get("media.class") == "Audio/Source"
               and o["info"]["props"].get("node.name") != EC_MIC]
    names = [p.get("node.name") for p in sources]
    default = next((m["value"].get("name") for o in objs
                    if o.get("type") == "PipeWire:Interface:Metadata"
                    and o.get("props", {}).get("metadata.name") == "default"
                    for m in o.get("metadata", []) if m.get("key") == "default.audio.source"), None)
    usb = [n for n in names if n and n.startswith("alsa_input.usb-")]
    if usb:
        return usb[0]
    if default in names and default.startswith("alsa_input"):
        return default
    builtin = [p["node.name"] for p in sources if "Digital Microphone" in p.get("node.description", "")]
    alsa = [n for n in names if n and n.startswith("alsa_input")]
    return (builtin or alsa or [None])[0]


def open_mic(suppress: bool) -> tuple[subprocess.Popen, str]:
    """Start recording 16 kHz mono s16 from the picked mic, through the knarf mic (noise suppressed)
    when there is one and `suppress`. Returns the process and a description for the log."""
    objs = pw_dump()
    mic = pick_mic(objs)
    target, how = mic, mic or "the default mic"
    capture = pw_node(EC_CAPTURE, objs) if suppress else None
    if capture is not None:
        # point the noise suppressor's input at our mic, and record its cleaned-up output
        if mic:
            subprocess.run(["pw-metadata", str(capture), "target.object", mic],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        target, how = EC_MIC, f"{how} through the knarf mic (noise suppressed)"
    proc = subprocess.Popen(
        ["pw-record", *(["--target", target] if target else []),
         "--rate", str(RATE), "--channels", "1", "--format", "s16", "--raw", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return proc, how
