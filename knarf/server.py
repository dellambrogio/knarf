"""The local HTTP API that `talk` uses, and the events it shares with the UI thread.

    POST /say      body = text   (?wait=1 to block until spoken)
    POST /stop     stop speaking and clear the queue
    POST /listen   start listening (or stop, if already listening); the text is typed into the focused window
    POST /listen?wait=1   listen and return what was said ({"text": ...}) instead of typing it (MCP `listen`)
    POST /chat     start talking with Claude directly (or stop, if already talking): knarf/chat.py
    POST /toggle   show or hide the window (/show, /hide)
    POST /quit     quit knarf
    GET  /status
"""

import json
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .config import HOST, PORT

QUIT = threading.Event()
WINDOW_VISIBLE = threading.Event()
COMMANDS = queue.Queue()  # window commands from the HTTP thread: "toggle" | "show" | "hide"


def make_server(speaker, listener, chat):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _reply(self, code, obj):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if urlparse(self.path).path == "/status":
                self._reply(200, {"ok": True, "speaking": speaker.busy, "queued": speaker.pending(),
                                  "listening": listener.state, "window": WINDOW_VISIBLE.is_set(),
                                  "chat": chat.active})
            else:
                self._reply(404, {"ok": False})

        def do_POST(self):
            u = urlparse(self.path)
            n = int(self.headers.get("Content-Length") or 0)
            text = self.rfile.read(n).decode("utf-8", "replace").strip()
            if u.path == "/say":
                if not text:
                    return self._reply(400, {"ok": False, "error": "empty text"})
                wait = parse_qs(u.query).get("wait", ["0"])[0] not in ("0", "", "false")
                done = threading.Event() if wait else None
                speaker.say(text, done)
                if done:
                    done.wait()
                self._reply(200, {"ok": True})
            elif u.path == "/listen":
                q = parse_qs(u.query)
                if q.get("wait", ["0"])[0] not in ("0", "", "false"):
                    timeout = float(q.get("timeout", ["0"])[0]) or None
                    text = listener.listen(timeout)
                    if text is None:
                        return self._reply(409, {"ok": False, "error": "already listening"})
                    return self._reply(200, {"ok": True, "text": text})
                listener.toggle()
                self._reply(200, {"ok": True, "listening": listener.state})
            elif u.path == "/chat":
                if not chat.available():
                    return self._reply(503, {"ok": False, "error": "claude not found"})
                chat.toggle()
                self._reply(200, {"ok": True})
            elif u.path == "/stop":
                speaker.stop()
                self._reply(200, {"ok": True})
            elif u.path == "/quit":
                QUIT.set()
                self._reply(200, {"ok": True})
            elif u.path in ("/toggle", "/show", "/hide"):
                COMMANDS.put(u.path[1:])
                self._reply(200, {"ok": True})
            else:
                self._reply(404, {"ok": False})

    return ThreadingHTTPServer((HOST, PORT), Handler)
