# Example: working with Claude Code by voice

`just mcp` is all Claude Code needs to speak and listen through Knarf. This folder adds two optional pieces on top,
as an example of one way to use it. They live here, not in a `.claude` folder, so Claude Code doesn't load them
while you work on Knarf itself: copy them into your own `~/.claude` to use them.

- `skills/knarf/SKILL.md`: a `/knarf` skill. Claude listens, does what you ask, answers out loud and listens again,
  until you say you're done ("I'm done", "I'm finished", "that's all"). Code, diffs and paths go on screen, not in
  the voice; anything hard to undo still needs your yes.
- `hooks/knarf-echo.sh` with `settings.json`: shows the voice traffic in the terminal as hook messages, what
  Claude says before it's said (PreToolUse on `speak`) and what you said once it's heard (PostToolUse on
  `listen`). Needs `jq`.

## Install

`just claude-example` copies the skill and the hook into `~/.claude` and adds the hooks to
`~/.claude/settings.json`. It keeps any skill or hook of that name you already have, and doesn't add the hooks
twice. Or by hand: copy `skills/knarf` to `~/.claude/skills/`, `hooks/knarf-echo.sh` to `~/.claude/hooks/`, and
merge the `hooks` block of `settings.json` into `~/.claude/settings.json`.

Then start a new Claude Code session. Type `/knarf` to start talking, or `/knarf <what to start with>`.

Anything personal Claude should know when listening to you (an accent, names it'll mishear) goes in
`~/.config/knarf/instructions.md`, not in the skill.
