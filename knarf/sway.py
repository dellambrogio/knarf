"""Small sway IPC helpers (runtime only; nothing touches the sway config)."""

import json
import subprocess


def sway_sticky(on):
    subprocess.Popen(["swaymsg", f'[app_id="knarf"] sticky {"enable" if on else "disable"}'],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def sway_focused_id():
    """con_id of the focused sway window, or None."""
    try:
        tree = json.loads(subprocess.run(["swaymsg", "-t", "get_tree", "-r"], capture_output=True,
                                         timeout=1).stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    stack = [tree]
    while stack:
        n = stack.pop()
        if n.get("focused") and n.get("type") in ("con", "floating_con"):
            return n["id"]
        stack += n.get("nodes", []) + n.get("floating_nodes", [])
    return None


def sway_focus(con_id):
    subprocess.Popen(["swaymsg", f"[con_id={con_id}] focus"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def sway_center(title, width, height):
    """Float the knarf window with this title at the given size, centred on the screen."""
    crit = f'[app_id="^knarf$" title="^{title}$"]'
    subprocess.Popen(["swaymsg", f"{crit} floating enable, border pixel 1, resize set {width} {height}, "
                                 "move position center"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
