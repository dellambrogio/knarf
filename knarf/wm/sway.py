"""sway, through `swaymsg` at runtime (nothing touches the sway config): the same IPC as i3."""

from .i3 import I3


class Sway(I3):
    name = "sway"
    msg = "swaymsg"
    match = "app_id"  # Wayland: the app_id, "knarf" (GLib prgname)
