# knarf

A little window that talks: a single green circle on black that glows with the voice.

    ./install.sh        # links `knarf` and `talk` into ~/.local/bin and adds a desktop launcher
    knarf &             # start the window
    talk "Hello there"  # make it speak (also: echo hi | talk, talk -w, talk --stop, talk --status)

In the window: Esc stops speaking, Ctrl+Q quits.

Listening (speech to text): press the global shortcut (`talk --listen`, bound to Super+\ in sway), or click the
circle / press Space in the window. The circle turns into a ring while it listens, stops when you go quiet,
transcribes locally with faster-whisper and types the text into the focused window with `wtype`. If you started
it by clicking the circle, the text is typed once you switch to another window. Run it again to stop early.

Settings: right-click the window, press `S`, or click the gear that appears top-right on hover.
Speed, volume, pause between sentences, voice (any `.onnx` in `~/.local/share/piper`), colour,
circle size, always-on-top, and for listening: language (default English), Whisper model, silence timeout and
whether to press Enter after typing. Changes apply immediately and are saved to `~/.config/knarf/settings.json`.
Requires Piper in `~/.local/share/piper` (its venv provides numpy, piper-tts and faster-whisper), `pw-play`,
`arecord` and `wtype`.
Environment: `KNARF_SPEED` (Piper length scale at 100% speed, default 1.3), `KNARF_PORT` (default 47820), `KNARF_MODEL`.
