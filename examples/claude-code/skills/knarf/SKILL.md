---
name: knarf
description: Work with Claude by voice through knarf. Claude keeps listening and answering out loud, doing the work as asked, until the user says they're done.
argument-hint: "[what to start with]"
disable-model-invocation: true
---

# Working by voice

From now on, the conversation happens out loud through knarf: `speak` to talk, `listen` to hear the user. It's
the same work as usual (reading code, editing, running commands, answering questions); only the channel changes.
If `$ARGUMENTS` is given, start with that. Otherwise say a short hello and ask what we're working on.

## The loop

- Each turn: `listen`, then do what was asked (with tools, as usual), then `speak` the outcome, then `listen`
  again. Keep going: **don't end your reply** between exchanges. The loop ends only when the user says they're
  done (see below).
- `speak` without `wait`: `listen` already waits for the speech to finish.
- **Before slow work** (many tool calls, a build, a long search), say what you're about to do in a sentence
  ("Let me look at the config"), so the silence isn't confusing. Don't narrate every tool call.
- If a request is unclear or a transcript doesn't make sense, ask, rather than guessing.

## Speaking and writing

- Speak for the ear: a few short sentences, the gist only. No markdown, symbols, paths, URLs or code; numbers and
  names as they're said ("the sway config", "version two point one").
- What doesn't work by ear goes **in writing** in the terminal, with a spoken pointer ("the diff is on screen"):
  code, diffs, paths, commands, lists, tables, error messages.
- Write the usual short written answer too, so there's a record.

## Transcripts

- Speech-to-text mishears names and technical words, more so with an accent. Read transcripts charitably. If a misheard word changes what you'd do, ask them to repeat it, or to type it if it's
  a name, a path, code or a number.
- `listen` returns when they pause, so one thought can arrive in pieces. If a transcript is clearly unfinished
  (cut mid-sentence), `listen` again before acting.

## Confirming

Before anything hard to undo or outward-facing (deleting, overwriting, committing, pushing, sending messages),
say what you're about to do and wait for a clear yes. A clear "commit it" or "push it" counts as the yes. Same
rules as when typing; voice doesn't lower the bar.

## Silence

If `listen` hears nothing, `listen` again: silence is fine, they may be thinking or away for a moment. After
about ten empty listens in a row, say "I'm still here" once and keep listening. After about twenty, stop the
loop with a short written line: they can type, or call `/knarf` again.

## Ending

- The loop ends when the user says they're done: "I'm done", "I'm finished", "that's all", "we're done",
  "stop listening", "bye", and the like.
- Only when it's meant as ending the session, not "I'm done with this file, now let's...". If unsure, ask
  "Shall I stop listening?"
- To end: speak a one-sentence goodbye (with anything left open, e.g. "the change isn't committed yet"), write
  the same in the terminal, and end your reply. Don't `listen` again.
- If they type a message instead of talking, handle it and resume the voice loop, unless it says they're done.
