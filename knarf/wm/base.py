"""What Knarf needs from the window manager.

On Wayland an app can't place its own windows, keep them out of the keyboard focus or show them on every
workspace: the compositor decides. So Knarf asks it, through one of these. Methods never raise: when the
window manager can't do something, it just doesn't happen.
"""

from abc import ABC, abstractmethod


class WindowManager(ABC):
    """The window manager, as Knarf's windows (app_id `app_id`) need it."""

    name = "base"

    def __init__(self, app_id: str = "knarf") -> None:
        self.app_id = app_id

    @abstractmethod
    def focused_window(self) -> object | None:
        """A handle for the window that has the keyboard focus now, None if unknown."""

    @abstractmethod
    def focus_window(self, handle: object) -> None:
        """Give the keyboard focus back to `handle` (from focused_window): the circle pops up without
        taking it, so dictation still types into the window you were in."""

    @abstractmethod
    def set_sticky(self, on: bool) -> None:
        """Show Knarf's windows on all workspaces, or only on one."""

    def on_workspace_change(self, callback) -> None:
        """Call `callback()` (from another thread) whenever you switch to another workspace. Default: never."""

    def move_to_current_workspace(self) -> None:
        """Move the circle to the workspace you're on, so it follows you while it's up. Default: nothing."""

    @abstractmethod
    def place_window(self, position: str, width: int, height: int) -> None:
        """Move the circle (a `width` x `height` window) to `position` on the focused screen: "center",
        "top", "bottom", or a corner like "bottom-right" (config.POSITIONS)."""

    @abstractmethod
    def center_window(self, title: str, width: int, height: int) -> None:
        """Float the Knarf window called `title` at this size in the middle of the screen."""
