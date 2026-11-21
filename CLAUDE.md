# knarf

A Tk window (`knarf.py`) that speaks text with Piper (`~/.local/share/piper`, voice en_US-lessac-medium)
and shows a single green circle on black that glows with the voice. It listens on http://127.0.0.1:47820.
User settings (speed, volume, voice, colour, size, on-top) live in `~/.config/knarf/settings.json`; edit them in the
window (right-click, `S`, or the gear icon).

It can also listen: `talk --listen` (Super+\ in sway) records until silence, transcribes with faster-whisper
(language English by default) and types into the focused window.

## Talking

When the user asks Claude to talk, use the user-level `talk` skill (`~/dotfiles/.claude/skills/talk/SKILL.md`,
managed in dotfiles). Keep it in sync when `talk`'s options or knarf's behaviour change.
