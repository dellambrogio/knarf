# Knarf

A transparent, borderless GTK4 window (native Wayland, app_id `knarf`) that speaks text with Piper (`~/.local/share/piper`, voice en_US-lessac-medium)
and shows only green lights that move with the voice (three bars, or a circle: the `style` setting). It listens on http://127.0.0.1:47820. It runs
all the time as the systemd user service `knarf.service` (tray icon via StatusNotifierItem; the window pops up while
speaking/listening). After changing the code: `just restart`.
User settings (speed, volume, voice, colour, style, size, position, sticky) live in `~/.config/knarf/settings.json`; edit them in the
window (right-click or `S`). GTK comes from the system's python3-gi (see `knarf/gtk.py`), the rest from the
Piper venv.

It can also listen: `talk --listen` (Super+\ in sway) records until silence, transcribes with faster-whisper
(language English by default) and types into the focused window.

## Layout

- `knarf/`: the package. `config` (paths, constants, Settings, listening tuning), `speaker` (Piper TTS, pipelined,
  compressed), `listener` (hektor-style speech detection + whisper STT),
  `server` (HTTP API + events shared with the UI), `gtk` (GTK imports), `wm/` (window manager: `base.py` is the
  `WindowManager` interface, `sway.py` and `none.py` implement it, `detect()` picks one), `style` (CSS),
  `tray` (StatusNotifierItem + dbusmenu), `window` (the `Circle` window), `panel` (settings window).
- `apps/gui.py`: the program; `bin/knarf` runs it with the Piper venv and `PYTHONPATH` set to the repo.
- `apps/mcp_server.py` (`bin/knarf-mcp`): the MCP server for Claude Code (speak, listen, stop, status), stdlib only;
  registered with `just mcp`.
- `knarf/audio.py`: mic helpers ported from [hektor](https://github.com/dellambrogio/hektor)
  (`app/hektor/audio_in.py`): voicing, high-pass,
  mic picking, the PipeWire noise-suppressed "Knarf mic" (`pipewire/`, `just audio-setup`).
- `bin/talk`: the CLI client.

Knarf is only an extension to Claude Code: it speaks and listens for Claude, it never calls Claude itself.

## Talking

Claude talks and listens through Knarf's MCP tools (`speak`, `listen`, `stop`, `status`); how and when to use
them is in `apps/mcp_server.py` (the server instructions and tool descriptions). Keep those in sync when Knarf's
behaviour changes. There is no skill for it.
