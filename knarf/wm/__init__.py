"""Window manager support: the WindowManager interface (base.py) and one class per window manager.

`detect()` picks the one for this session; anything unknown gets NoWindowManager, which does nothing.
To support another one, subclass WindowManager in a module here and add it to `detect()`.
"""

import os
import shutil
import subprocess

from .base import WindowManager
from .i3 import I3
from .none import NoWindowManager
from .sway import Sway

__all__ = ["WindowManager", "NoWindowManager", "I3", "Sway", "detect"]


def detect(app_id: str = "knarf") -> WindowManager:
    if os.environ.get("SWAYSOCK") and shutil.which("swaymsg"):
        return Sway(app_id)
    if shutil.which("i3-msg") and (os.environ.get("I3SOCK") or _i3_running()):
        return I3(app_id)
    return NoWindowManager(app_id)


def _i3_running() -> bool:
    """i3 is this X session's window manager (i3-msg finds it through the X root window, as a service too)."""
    if not os.environ.get("DISPLAY"):
        return False
    try:
        return subprocess.run(["i3-msg", "-t", "get_version"], capture_output=True, timeout=1).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False
