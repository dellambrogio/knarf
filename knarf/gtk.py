"""GTK4 imports.

PyGObject doesn't build inside the Piper venv without system dev headers, so borrow the
system's bindings (apt: python3-gi, python3-gi-cairo, gir1.2-gtk-4.0). The path is appended
last, so the venv's own packages still win.
"""

import sys

try:
    import gi
except ImportError:
    sys.path.append("/usr/lib/python3/dist-packages")
    import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
import cairo  # noqa: E402
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

__all__ = ["cairo", "Gdk", "Gio", "GLib", "Gtk"]
