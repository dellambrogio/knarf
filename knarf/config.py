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
    "volume": 100,     # percent of full level: the voice is evened out and its peaks brought to this
    "pause": 0.35,     # seconds between sentences
    "caption_hold": 3.0,  # seconds the last spoken sentence stays under the circle
    "voice": os.path.basename(MODEL),
    "color": "green",
    "size": 100,       # percent
    "style": "circle", # how knarf looks: one of STYLES
    "sticky": False,      # show on all workspaces (sway)
    "popup": True,        # show the circle while speaking or listening, hide it after
    "position": "center", # where the circle shows: one of POSITIONS
    "language": "en",     # whisper language code, or "auto" to detect
    "stt_model": "small", # whisper model size
    "silence": 1.2,       # seconds of silence that end a recording
    "send_enter": False,  # press Enter after typing the transcript
    "noise_suppression": True,  # record through the knarf mic (`just audio-setup`) when it's there
}
STYLES = ["circle", "bars"]
POSITIONS = ["center", "top", "bottom", "top-left", "top-right", "bottom-left", "bottom-right"]
LANGUAGES = ["auto", "en", "it", "de", "fr", "es"]
STT_MODELS = ["tiny", "base", "small", "medium"]

# Telling talking from noise (hektor's tuning; see knarf/listener.py)
SPEECH_RUN = 3       # talking = this many of the last SPEECH_RUN + 2 chunks (100 ms) loud and voiced
VOICED = 0.6         # how voiced (0-1) a chunk must be: vowels ~0.6-1; fans, hiss, key clicks, thumps ~0.2-0.45
NOISE_FACTOR = 2.5   # loud = over the background noise x this
MIN_RMS = 15         # lowest speech threshold, for very quiet rooms
SILENCE_SHARE = 0.2  # quiet = under this share of your speech's typical loudness (or the threshold)
NO_SPEECH = 8        # seconds: give up if nothing is said
MAX_LEN = 120        # seconds: longest recording
MIC_HIGHPASS = 300   # Hz, cuts hum and fan noise below it; 0 = off


def voices():
    return sorted(os.path.basename(p) for p in glob.glob(os.path.join(PIPER_DIR, "*.onnx")))


# Piper's voice files don't say whether a voice is male or female: the ones knarf offers (`just voices`)
VOICE_GENDERS = {"lessac": "female", "amy": "female", "hfc_female": "female", "jenny_dioco": "female",
                 "cori": "female", "ryan": "male", "joe": "male", "alan": "male", "hfc_male": "male"}
VOICE_ACCENTS = {"en_US": "American", "en_GB": "British"}


def voice_label(filename):
    """en_GB-jenny_dioco-medium.onnx -> 'Jenny Dioco (British, female)'."""
    try:
        lang, speaker, quality = filename.removesuffix(".onnx").split("-")
    except ValueError:
        return filename
    name = "HFC" if speaker.startswith("hfc_") else speaker.replace("_", " ").title()
    details = [VOICE_ACCENTS.get(lang, lang), VOICE_GENDERS.get(speaker), "high quality" if quality == "high" else None]
    return f"{name} ({', '.join(d for d in details if d)})"


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
