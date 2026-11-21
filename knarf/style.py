"""Colours and CSS: a transparent circle window, a green-on-black settings panel."""

from .config import COLORS
from .gtk import Gdk, Gtk


def hexcolor(rgb, k=1.0):
    return "#%02x%02x%02x" % tuple(int(max(0, min(255, v * k))) for v in rgb)


def apply_css(color_name):
    """(Re)style everything: transparent main window, green-on-black settings panel."""
    rgb = COLORS[color_name]
    fg, dim = hexcolor(rgb), hexcolor(rgb, 0.35)
    swatches = "\n".join(f"window.knarf-settings button.swatch-{n} {{ background: {hexcolor(c)}; }}"
                         for n, c in COLORS.items())
    css = f"""
    window.knarf-main, window.knarf-main > * {{ background: transparent; box-shadow: none; }}
    window.knarf-settings, window.knarf-settings popover contents {{
        background: #000000; color: {fg}; font-size: 10pt; }}
    window.knarf-settings label {{ color: {fg}; }}
    window.knarf-settings scale trough {{ background: {dim}; min-height: 3px; border: none; }}
    window.knarf-settings scale highlight {{ background: {fg}; border: none; min-height: 3px; min-width: 3px; margin: 0; }}
    window.knarf-settings scale slider {{ background: {fg}; min-width: 12px; min-height: 12px;
        margin: -5px; border: none; box-shadow: none; border-radius: 6px; }}
    window.knarf-settings scale value {{ color: {fg}; }}
    window.knarf-settings button, window.knarf-settings dropdown > button {{
        background: #000000; background-image: none; color: {fg}; border: 1px solid {dim};
        box-shadow: none; border-radius: 3px; }}
    window.knarf-settings button:hover {{ background: #0c0c0c; }}
    window.knarf-settings popover row:hover, window.knarf-settings popover row:selected {{ background: {dim}; }}
    window.knarf-settings check {{ background: #000000; border: 1px solid {dim}; color: #000000; }}
    window.knarf-settings check:checked {{ background: {fg}; }}
    window.knarf-settings button.swatch {{ min-width: 18px; min-height: 18px; padding: 0; border-radius: 50%;
        border: 3px solid #000000; outline: none; }}
    window.knarf-settings button.swatch.selected {{ border-color: #000000; box-shadow: 0 0 0 2px {fg}; }}
    {swatches}
    """
    global _css
    display = Gdk.Display.get_default()
    if "_css" in globals():
        Gtk.StyleContext.remove_provider_for_display(display, _css)
    _css = Gtk.CssProvider()
    _css.load_from_string(css)
    Gtk.StyleContext.add_provider_for_display(display, _css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
