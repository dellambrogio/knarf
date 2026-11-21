# knarf

A little window that talks: a single green circle on black that glows with the voice.

    ./install.sh        # links `knarf` and `talk` into ~/.local/bin and adds a desktop launcher
    knarf &             # start the window
    talk "Hello there"  # make it speak (also: echo hi | talk, talk -w, talk --stop, talk --status)

In the window: Esc stops speaking, Ctrl+Q quits.
Requires Piper in `~/.local/share/piper` (its venv provides numpy and piper-tts) and `pw-play`.
Environment: `KNARF_SPEED` (length scale, default 1.3), `KNARF_PORT` (default 47820), `KNARF_MODEL`.
