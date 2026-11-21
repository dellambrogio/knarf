"""Window manager support: the WindowManager interface (base.py) and one class per window manager.

`detect()` picks the one for this session; anything unknown gets NoWindowManager, which does nothing.
To support another one, subclass WindowManager in a module here and add it to `detect()`.
"""

import os
import shutil

from .base import WindowManager
from .none import NoWindowManager
from .sway import Sway

__all__ = ["WindowManager", "NoWindowManager", "Sway", "detect"]


def detect(app_id: str = "knarf") -> WindowManager:
    if os.environ.get("SWAYSOCK") and shutil.which("swaymsg"):
        return Sway(app_id)
    return NoWindowManager(app_id)
