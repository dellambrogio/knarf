#!/usr/bin/env python3
"""Redraw docs/circle.png: the circle in its four states, drawn by the real drawing code (Circle._draw)
into an image, so nothing on the desktop shows through. Run with `just screenshots`.
docs/settings.png is a capture of the real settings window."""

import sys
import time
import types
from pathlib import Path

from knarf.config import Settings
from knarf.gtk import cairo
from knarf.window import Circle

W = H = 300
LABEL = 40
STATES = [  # label, listener state, voice level, speaking, mic level
    ("ready", "idle", 0.0, 0.0, 0.0),
    ("speaking", "idle", 0.75, 1.0, 0.0),
    ("listening", "listening", 0.0, 0.0, 0.5),
    ("transcribing", "thinking", 0.0, 0.0, 0.0),
]


def main(path: str) -> None:
    st = Settings()
    out = cairo.ImageSurface(cairo.FORMAT_ARGB32, W * len(STATES), H + LABEL)
    cr = cairo.Context(out)
    cr.set_source_rgb(0, 0, 0)
    cr.paint()
    for i, (label, state, level, active, mic) in enumerate(STATES):
        fake = types.SimpleNamespace(level=level, active=active, mic=mic, st=st,
                                     ls=types.SimpleNamespace(state=state), t0=time.monotonic() - 1.3)
        tile = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
        Circle._draw(fake, None, cairo.Context(tile), W, H)
        cr.set_source_surface(tile, i * W, 0)
        cr.paint()
        cr.select_font_face("monospace")
        cr.set_font_size(16)
        ext = cr.text_extents(label)
        cr.set_source_rgb(0.2, 1.0, 0.4)
        cr.move_to(i * W + (W - ext.width) / 2, H + 24)
        cr.show_text(label)
    out.write_to_png(path)
    print("wrote", path)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).resolve().parent.parent / "docs" / "circle.png"))
