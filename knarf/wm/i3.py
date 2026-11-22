"""i3, through `i3-msg` at runtime (nothing touches the i3 config). sway speaks the same IPC, so `Sway` is this
with `swaymsg`, matching windows by their Wayland app_id instead of their X11 instance (both "knarf")."""

import json
import subprocess
import threading
import time

from .base import WindowManager


class I3(WindowManager):
    name = "i3"
    msg = "i3-msg"       # the IPC client
    match = "instance"   # the criterion that matches Knarf's windows (WM_CLASS instance = prgname "knarf")

    def _run(self, command: str) -> None:
        try:
            subprocess.Popen([self.msg, command], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass

    def focused_window(self) -> int | None:
        """con_id of the focused window."""
        try:
            tree = json.loads(subprocess.run([self.msg, "-t", "get_tree", "-r"], capture_output=True,
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
        self._run(f'[{self.match}="^{self.app_id}$"] sticky {"enable" if on else "disable"}')

    def on_workspace_change(self, callback) -> None:
        def watch():  # i3-msg / swaymsg print one JSON event per line; started again if it goes away (WM restarted, ...)
            while True:
                try:
                    with subprocess.Popen([self.msg, "-t", "subscribe", "-m", '["workspace"]'],
                                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True) as p:
                        for line in p.stdout:
                            try:
                                if json.loads(line).get("change") == "focus":
                                    callback()
                            except ValueError:
                                pass
                except OSError:
                    pass
                time.sleep(2)

        threading.Thread(target=watch, daemon=True).start()

    def _focused_workspace(self) -> str | None:
        try:
            spaces = json.loads(subprocess.run([self.msg, "-t", "get_workspaces", "-r"], capture_output=True,
                                               timeout=1).stdout)
            return next(w["name"] for w in spaces if w.get("focused"))
        except (OSError, ValueError, StopIteration, KeyError, subprocess.TimeoutExpired):
            return None

    def move_to_current_workspace(self) -> None:
        name = self._focused_workspace()
        if name is not None:
            name = name.replace("\\", "\\\\").replace('"', '\\"')
            self._run(f'[{self.match}="^{self.app_id}$" title="^knarf$"] move container to workspace "{name}"')

    def place_window(self, position: str, width: int, height: int) -> None:
        # the focused workspace's area, which leaves out bars (i3bar, waybar)
        try:
            spaces = json.loads(subprocess.run([self.msg, "-t", "get_workspaces", "-r"], capture_output=True,
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
        self._run(f'[{self.match}="^{self.app_id}$" title="^knarf$"] '
                  f"floating enable, border none, resize set {width} {height}, move absolute position {x} {y}")

    def center_window(self, title: str, width: int, height: int) -> None:
        # a rule for the circle (in the config) may also catch other Knarf windows: put this one back
        crit = f'[{self.match}="^{self.app_id}$" title="^{title}$"]'
        self._run(f"{crit} floating enable, border pixel 1, resize set {width} {height}, move position center")
