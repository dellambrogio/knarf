#!/usr/bin/env python3
"""knarf's MCP server: gives Claude Code a voice and ears through the running knarf.

Tools: speak, listen, stop, status. Stdio JSON-RPC (one message per line), standard library only;
it talks to knarf over its local HTTP API (knarf/server.py) and starts the systemd service if knarf
isn't running. Registered for all projects with `just mcp`.
"""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

URL = f"http://127.0.0.1:{os.environ.get('KNARF_PORT', '47820')}"

INSTRUCTIONS = """knarf is the user's local voice extension: a speaker and a microphone on their desktop.
Use `speak` when the user asks you to talk, say something out loud, read something aloud, or answer by voice.
Use `listen` to hear the user's spoken answer, typically right after asking them a question with `speak`
(wait=true). Transcripts may have small errors: read them charitably and ask again if something is unclear.
Keep giving your normal written answer too unless the user asked for voice only."""

# Anything personal for Claude (an accent, names it should know, ...) goes in this private file, not the repo.
PRIVATE = os.path.expanduser("~/.config/knarf/instructions.md")

SPEAK_HOW = ("Write for the ear: plain spoken sentences, no markdown, bullets, code, file paths, URLs or tables "
             "(say 'the config file', not a path). Keep it to a few sentences: the gist, details stay in the "
             "written reply. Write numbers and symbols as they're said ('version two point one', not 'v2.1'). "
             "Put each thought in its own sentence: it's spoken a sentence at a time.")

TOOLS = [
    {
        "name": "speak",
        "description": "Say text out loud through knarf. " + SPEAK_HOW,
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "What to say."},
                "wait": {"type": "boolean", "default": False,
                         "description": "Return only once it has been spoken (use before `listen`)."},
            },
            "required": ["text"],
        },
    },
    {
        "name": "listen",
        "description": ("Listen to the user through the microphone and return what they said, transcribed. "
                        "Recording ends when they go quiet; returns an empty result if they said nothing "
                        "within about 8 seconds. Use it after asking a question with `speak` (wait=true)."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "timeout": {"type": "number", "default": 120,
                            "description": "Give up after this many seconds."},
            },
        },
    },
    {
        "name": "stop",
        "description": "Stop speaking now and drop anything still queued.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "status",
        "description": "Whether knarf is running, speaking or listening.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def instructions() -> str:
    try:
        with open(PRIVATE) as f:
            extra = f.read().strip()
    except OSError:
        extra = ""
    return INSTRUCTIONS + ("\n\n" + extra if extra else "")


def call(method: str, path: str, body: bytes | None = None, timeout: float = 10) -> dict:
    req = urllib.request.Request(URL + path, data=body, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return json.load(e)


def ensure_running() -> None:
    """Start knarf's systemd service if it isn't answering, and wait for it."""
    try:
        call("GET", "/status", timeout=1)
        return
    except OSError:
        pass
    subprocess.run(["systemctl", "--user", "start", "knarf.service"], capture_output=True)
    for _ in range(60):
        time.sleep(0.5)
        try:
            call("GET", "/status", timeout=1)
            return
        except OSError:
            pass
    raise RuntimeError("knarf isn't running and didn't start (systemctl --user status knarf)")


def run_tool(name: str, args: dict) -> str:
    ensure_running()
    if name == "speak":
        text = str(args.get("text", "")).strip()
        if not text:
            raise ValueError("nothing to say")
        wait = bool(args.get("wait"))
        call("POST", "/say?wait=1" if wait else "/say", text.encode(), timeout=600 if wait else 10)
        return "Spoken." if wait else "Speaking."
    if name == "listen":
        timeout = float(args.get("timeout") or 120)
        r = call("POST", f"/listen?wait=1&timeout={timeout}", b"", timeout=timeout + 15)
        if not r.get("ok"):
            raise RuntimeError(r.get("error", "listening failed"))
        return r["text"] or "(nothing heard)"
    if name == "stop":
        call("POST", "/stop", b"")
        return "Stopped."
    if name == "status":
        return json.dumps(call("GET", "/status"))
    raise ValueError(f"unknown tool {name}")


def handle(msg: dict) -> dict | None:
    method, mid = msg.get("method"), msg.get("id")
    if mid is None:  # a notification (initialized, cancelled, ...): no answer
        return None
    if method == "initialize":
        version = msg.get("params", {}).get("protocolVersion", "2025-06-18")
        result = {"protocolVersion": version, "capabilities": {"tools": {}},
                  "serverInfo": {"name": "knarf", "version": "1.0"}, "instructions": instructions()}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        p = msg.get("params", {})
        try:
            text, error = run_tool(p.get("name", ""), p.get("arguments") or {}), False
        except Exception as e:  # report to Claude, keep serving
            text, error = f"knarf: {e}", True
        result = {"content": [{"type": "text", "text": text}], "isError": error}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"no method {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def main() -> None:
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            reply = handle(json.loads(line))
        except ValueError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
