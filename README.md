# knarf

A little window that talks: a single green circle that glows with the voice. The window is transparent and
borderless, so only the green shows.

    just install        # deps, voice, `knarf` + `talk` in ~/.local/bin, launcher, and the systemd user service
    just sway-bind      # optional: Super+\ = push-to-talk in sway
    just logs           # follow the service log (just restart after code changes)
    talk "Hello there"  # make it speak (also: echo hi | talk, talk -w, talk --stop, talk --status)
    talk --toggle       # show or hide the circle (talk --quit quits knarf)

In the window: click to listen, middle-click stops speaking, right-click or S opens settings, Esc stops speaking,
Ctrl+Q quits.

Listening (speech to text): press the global shortcut (`talk --listen`, bound to Super+\ in sway), or click the
circle / press Space in the window. The circle turns into a ring while it listens, stops when you go quiet,
transcribes locally with faster-whisper and types the text into the focused window with `wtype`. If you started
it by clicking the circle, the text is typed once you switch to another window. Run it again to stop early.

Settings: right-click the circle or press `S`.
Speed, volume, pause between sentences, voice (any `.onnx` in `~/.local/share/piper`), colour,
circle size, show on all workspaces (sway sticky), and for listening: language (default English), Whisper model, silence timeout and
whether to press Enter after typing. Changes apply immediately and are saved to `~/.config/knarf/settings.json`.
Requires Piper in `~/.local/share/piper` (its venv provides numpy, piper-tts and faster-whisper), `pw-play`,
`arecord`, `wtype`, and GTK4 Python bindings from apt (python3-gi, python3-gi-cairo, gir1.2-gtk-4.0), which knarf
borrows from the system Python since PyGObject doesn't build in the venv without dev headers.
Environment: `KNARF_SPEED` (Piper length scale at 100% speed, default 1.3), `KNARF_PORT` (default 47820), `KNARF_MODEL`.

`just uninstall` removes the commands, launcher and sway binding (Piper, models and settings are kept).

Always running: `just service` installs a systemd user service (`~/.config/systemd/user/knarf.service`), so knarf
starts with your session and restarts if it crashes; nothing is added to the sway config. It lives in waybar's tray
like other background apps: left-click shows/hides the circle, middle-click listens, right-click opens a menu (show/hide,
listen, stop speaking, settings, restart, quit). The tray icon is a green dot, glowing while speaking, a red ring while
listening, yellow while transcribing. The circle is hidden by default and pops up while knarf speaks or listens
(setting "Pop up while speaking or listening"), without taking keyboard focus. Quitting from the tray stops it until
the next login (or `systemctl --user start knarf`).

Code: the `knarf/` package (config, speaker, listener, server, gtk, sway, style, tray, window, panel) and the
program in `apps/gui.py`, started by `bin/knarf`.
