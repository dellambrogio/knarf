"""No window manager support: everything is left to the desktop's defaults."""

from .base import WindowManager


class NoWindowManager(WindowManager):
    name = "none"

    def focused_window(self) -> object | None:
        return None

    def focus_window(self, handle: object) -> None:
        pass

    def set_sticky(self, on: bool) -> None:
        pass

    def center_window(self, title: str, width: int, height: int) -> None:
        pass
