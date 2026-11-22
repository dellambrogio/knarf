"""Talking with Claude directly (standalone mode), ported from hektor's brain.

Knarf listens, asks Claude Code (`claude -p`, on your claude.ai login: no API key), speaks the answer as it streams
in, and listens again, in the same conversation, until you say you're done ("I'm done", "that's all", "bye").

It's Claude only: no tools, no MCP servers, so it answers from what it knows. Claude runs without a terminal here,
so nobody could approve a tool anyway.
"""

import json
import os
import re
import shutil
import subprocess
import threading
import uuid

from .speaker import SENTENCE_END

PROMPT = """You're talking with the user out loud, through Knarf: everything you write is spoken, and what they say
reaches you through speech-to-text, which can mishear words (read it charitably; ask if something is unclear).
Answer like in a conversation: a few short spoken sentences, the gist first. No markdown, lists, code, links or
tables; numbers and symbols as they're said. In this mode you have no tools: you can't look things up, read their
files or change anything, so answer from what you know, and if they ask for more, say so briefly. When they're done,
they say so and Knarf ends the conversation; you don't need to."""

# Extra instructions for Claude, from a private file outside the repo (the MCP server reads it too).
PRIVATE = os.path.expanduser("~/.config/knarf/instructions.md")

DONE = re.compile(r"^(?:(?:ok(?:ay)?|alright|so|well|thanks|thank you)[ ,]+)*"
                  r"(?:(?:i'?m|i am|we'?re|we are) (?:all )?(?:done|finished)|that'?s (?:all|it)|stop listening"
                  r"|(?:good)?bye|see you)\b")
SILENT_LIMIT = 15  # empty listens in a row (about 8 s each) before Knarf stops by itself


def is_done(text: str) -> bool:
    """`text` ends the conversation: a short "I'm done", "that's all", "bye"... (not "I'm done with this, now...")."""
    t = " ".join(re.sub(r"[^\w' ,]", " ", text.lower()).split())
    return len(t.split()) <= 6 and bool(DONE.match(t))


def claude_path() -> str | None:
    """The `claude` command. The systemd service's PATH doesn't have ~/.local/bin, where it usually is."""
    local = os.path.expanduser("~/.local/bin/claude")
    return shutil.which("claude") or (local if os.access(local, os.X_OK) else None)


def prompt() -> str:
    try:
        with open(PRIVATE) as f:
            extra = f.read().strip()
    except OSError:
        extra = ""
    return PROMPT + ("\n\n" + extra if extra else "")


class Chat:
    """One spoken conversation with Claude at a time. `active` and `thinking` are read by the UI."""

    def __init__(self, speaker, listener):
        self.sp, self.ls = speaker, listener
        self.active = False    # a conversation is going
        self.thinking = False  # waiting for Claude
        self.stop_flag = False
        self.session = None
        self.proc = None

    def available(self) -> bool:
        return claude_path() is not None

    def toggle(self):
        if self.active:
            self.stop()
        else:
            self.start()

    def start(self):
        if self.active or not self.available():
            return
        self.active, self.stop_flag, self.session = True, False, None
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self):
        self.stop_flag = True
        p = self.proc
        if p and p.poll() is None:
            p.terminate()
        if self.ls.state == "listening":
            self.ls.stop_flag = True  # end the recording; what it hears is dropped
        self.sp.stop()

    # --- the conversation ---------------------------------------------------------
    def _say(self, text) -> threading.Event:
        done = threading.Event()
        self.sp.say(text, done)
        return done

    def _wait(self, done: threading.Event):
        while not done.wait(0.2) and not self.stop_flag:
            pass

    def _run(self):
        try:
            self._wait(self._say("Hi. What would you like to talk about?"))
            silent = 0
            while not self.stop_flag:
                text = self.ls.listen()
                if self.stop_flag:
                    break
                if text is None:  # the mic is busy (dictation): try again in a moment
                    threading.Event().wait(0.5)
                    continue
                if not text:
                    silent += 1
                    if silent >= SILENT_LIMIT:
                        self._wait(self._say("I'll stop listening now. Start me again when you need me."))
                        break
                    continue
                silent = 0
                print(f"knarf chat: you: {text}", flush=True)
                if is_done(text):
                    self._wait(self._say("Okay. Bye for now."))
                    break
                self._answer(text)
        except Exception as e:  # keep knarf alive no matter what
            print("knarf chat failed:", e, flush=True)
        finally:
            self.active = self.thinking = False
            self.proc = None

    def _answer(self, text):
        """Ask Claude and speak the answer a sentence at a time, as it streams in; return once it's spoken."""
        new = self.session is None
        if new:
            self.session = str(uuid.uuid4())
        cmd = [claude_path(), "-p", text, "--session-id" if new else "--resume", self.session,
               "--output-format", "stream-json", "--verbose", "--include-partial-messages",
               "--tools", "", "--strict-mcp-config",  # Claude only: no tools, no MCP servers
               "--append-system-prompt", prompt()]
        self.thinking = True
        buf, said, last, reply = "", False, None, ""
        try:
            self.proc = subprocess.Popen(cmd, cwd=os.path.expanduser("~"), stdin=subprocess.DEVNULL,
                                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            for line in self.proc.stdout:
                if self.stop_flag:
                    break
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                if msg.get("parent_tool_use_id"):  # a subagent's, not the answer
                    continue
                if msg.get("type") == "result":
                    reply = "" if msg.get("is_error") else (msg.get("result") or "")
                    continue
                if msg.get("type") != "stream_event":
                    continue
                ev = msg["event"]
                if ev.get("type") == "content_block_start" and buf.strip():
                    buf += "\n"  # a new block (after a tool) starts a new sentence
                if ev.get("type") == "content_block_delta" and ev["delta"].get("type") == "text_delta":
                    buf += ev["delta"]["text"]
                    ends = list(SENTENCE_END.finditer(buf))
                    if ends:  # speak the finished sentences, keep the rest
                        cut = ends[-1].end()
                        last, said = self._say(buf[:cut]), True
                        buf = buf[cut:]
                        self.thinking = False
            rc = self.proc.wait()
            if buf.strip() and not self.stop_flag:
                last, said = self._say(buf), True
            if not said and reply and not self.stop_flag:  # nothing streamed: the whole answer at once
                last, said = self._say(reply), True
            if not said and not self.stop_flag:
                err = self.proc.stderr.read().strip()[-300:]
                print(f"knarf chat: claude failed ({rc}): {err}", flush=True)
                if new:
                    self.session = None  # it may not exist: don't resume it next time
                last = self._say("Sorry, Claude didn't answer.")
        finally:
            self.thinking = False
        if last:
            self._wait(last)
