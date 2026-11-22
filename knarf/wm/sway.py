"""sway, through `swaymsg` at runtime (nothing touches the sway config)."""

import json
import subprocess

from .base import WindowManager


class Sway(WindowManager):
    name = "sway"

    def _run(self, command: str) -> None:
        try:
            subprocess.Popen(["swaymsg", command], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass

    def focused_window(self) -> int | None:
        """con_id of the focused window."""
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

    def focus_window(self, handle: object) -> None:
        self._run(f"[con_id={handle}] focus")

    def set_sticky(self, on: bool) -> None:
        self._run(f'[app_id="^{self.app_id}$"] sticky {"enable" if on else "disable"}')

    def place_window(self, position: str, width: int, height: int) -> None:
        # the focused workspace's area, which leaves out bars like waybar
        try:
            spaces = json.loads(subprocess.run(["swaymsg", "-t", "get_workspaces", "-r"], capture_output=True,
                                               timeout=1).stdout)
            r = next(w["rect"] for w in spaces if w.get("focused"))
        except (OSError, ValueError, StopIteration, KeyError, subprocess.TimeoutExpired):
            return
        margin = 10
        x = r["x"] + (r["width"] - width) // 2
        y = r["y"] + (r["height"] - height) // 2
        if "left" in position:
            x = r["x"] + margin
        if "right" in position:
            x = r["x"] + r["width"] - width - margin
        if position.startswith("top"):
            y = r["y"] + margin
        if position.startswith("bottom"):
            y = r["y"] + r["height"] - height - margin
        self._run(f'[app_id="^{self.app_id}$" title="^knarf$"] move absolute position {x} {y}')

    def center_window(self, title: str, width: int, height: int) -> None:
        # the rule for the circle (app_id knarf) also catches other Knarf windows: put this one back
        crit = f'[app_id="^{self.app_id}$" title="^{title}$"]'
        self._run(f"{crit} floating enable, border pixel 1, resize set {width} {height}, move position center")
