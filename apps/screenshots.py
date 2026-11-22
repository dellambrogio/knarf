#!/usr/bin/env python3
"""Redraw docs/states.png: Knarf in its four states, one row per style (bars, circle), drawn by the real drawing
code (Circle._draw) into an image, so nothing on the desktop shows through. Run with `just screenshots`.
docs/settings.png is a capture of the real settings window."""

import sys
from pathlib import Path

from knarf.config import STYLES, Settings
from knarf.gtk import cairo
from knarf.window import Circle

W = H = 300
ROW = 220  # rows are closer than the tiles are tall
LABEL = 40
STATES = [  # label, listener state, voice level, speaking, mic level
    ("ready", "idle", 0.0, 0.0, 0.0),
    ("speaking", "idle", 0.75, 1.0, 0.0),
    ("listening", "listening", 0.0, 0.0, 0.5),
    ("transcribing", "thinking", 0.0, 0.0, 0.0),
]


def main(path: str) -> None:
    st = Settings()
    out = cairo.ImageSurface(cairo.FORMAT_ARGB32, W * len(STATES), ROW * len(STYLES) + LABEL)
    cr = cairo.Context(out)
    cr.set_source_rgb(0, 0, 0)
    cr.paint()
    for row, style in enumerate(STYLES):
        for i, (label, state, level, active, mic) in enumerate(STATES):
            fake = Circle.offscreen(dict(st.data, style=style), state, level, active, mic, t=1.3)
            tile = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
            Circle._draw(fake, None, cairo.Context(tile), W, H)
            # tiles are transparent around the drawing, so the rows can overlap
            cr.set_source_surface(tile, i * W, row * ROW - (H - ROW) / 2)
            cr.paint()
    cr.select_font_face("monospace")
    cr.set_font_size(16)
    cr.set_source_rgb(0.2, 1.0, 0.4)
    for i, (label, *_rest) in enumerate(STATES):
        ext = cr.text_extents(label)
        cr.move_to(i * W + (W - ext.width) / 2, ROW * len(STYLES) + 24)
        cr.show_text(label)
    out.write_to_png(path)
    print("wrote", path)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).resolve().parent.parent / "docs" / "states.png"))
