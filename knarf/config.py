"""Paths, constants and the persistent settings."""

import glob
import json
import os

PIPER_DIR = os.path.expanduser("~/.local/share/piper")
MODEL = os.environ.get("KNARF_MODEL", os.path.join(PIPER_DIR, "en_US-lessac-medium.onnx"))
HOST = "127.0.0.1"
PORT = int(os.environ.get("KNARF_PORT", "47820"))
BASE_LENGTH = float(os.environ.get("KNARF_SPEED", os.environ.get("SAY_SPEED", "1.3")))  # piper length scale at 100% speed
PLAYER_LATENCY = 0.06  # rough pw-play startup latency, keeps visuals in sync
CONFIG = os.path.expanduser("~/.config/knarf/settings.json")

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
    "sticky": False,      # show on all workspaces (sway)
    "popup": True,        # show the circle while speaking or listening, hide it after
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
