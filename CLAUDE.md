# knarf

A transparent, borderless GTK4 window (native Wayland, app_id `knarf`) that speaks text with Piper (`~/.local/share/piper`, voice en_US-lessac-medium)
and shows only a green circle that glows with the voice. It listens on http://127.0.0.1:47820. It runs
all the time as the systemd user service `knarf.service` (tray icon via StatusNotifierItem; circle pops up while
speaking/listening). After changing the code: `just restart`.
User settings (speed, volume, voice, colour, size, sticky) live in `~/.config/knarf/settings.json`; edit them in the
window (right-click or `S`). GTK comes from the system's python3-gi (see `knarf/gtk.py`), the rest from the
Piper venv.

It can also listen: `talk --listen` (Super+\ in sway) records until silence, transcribes with faster-whisper
(language English by default) and types into the focused window.

## Layout

- `knarf/`: the package. `config` (paths, constants, Settings), `speaker` (Piper TTS), `listener` (whisper STT),
  `server` (HTTP API + events shared with the UI), `gtk` (GTK imports), `sway` (IPC helpers), `style` (CSS),
  `tray` (StatusNotifierItem + dbusmenu), `window` (the `Circle` window), `panel` (settings window).
- `apps/gui.py`: the program; `bin/knarf` runs it with the Piper venv and `PYTHONPATH` set to the repo.
- `bin/talk`: the CLI client.

## Talking

When the user asks Claude to talk, use the user-level `talk` skill (`~/dotfiles/.claude/skills/talk/SKILL.md`,
managed in dotfiles). Keep it in sync when `talk`'s options or knarf's behaviour change.
