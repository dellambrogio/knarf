#!/usr/bin/env python3
"""knarf: the always-on program (run by the systemd user service, or `knarf`).

Loads the voice, starts the speech-to-text listener and the local HTTP API for `talk`,
then runs the circle window (hidden until needed) with its tray icon.
"""

import queue
import threading

from knarf.chat import Chat
from knarf.config import HOST, PORT, Settings
from knarf.gtk import Gdk, Gio, GLib, Gtk
from knarf.listener import Listener
from knarf.server import make_server
from knarf.speaker import Speaker
from knarf.window import Circle


def main():
    # At login systemd can start us before sway has exported WAYLAND_DISPLAY. Without a display
    # GTK still runs but the window fails, so exit and let Restart=on-failure try again.
    Gtk.init_check()
    if Gdk.Display.get_default() is None:
        raise SystemExit("knarf: no display yet")
    settings = Settings()
    try:
        speaker = Speaker(settings)
    except Exception as e:
        raise SystemExit(f"knarf: could not load voice {settings.voice_path()}: {e}")
    inbox = queue.Queue()  # transcripts from the listener thread, consumed by the UI
    listener = Listener(settings, speaker, inbox.put)
    chat = Chat(speaker, listener)  # standalone mode: talking with Claude directly
    try:
        server = make_server(speaker, listener, chat)
    except OSError:
        raise SystemExit(f"knarf: port {PORT} is busy — is knarf already running?")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"knarf listening on http://{HOST}:{PORT}", flush=True)

    GLib.set_prgname("knarf")  # Wayland app_id, so sway can match the window
    gapp = Gtk.Application(flags=Gio.ApplicationFlags.NON_UNIQUE)
    gapp.connect("activate", lambda a: Circle(a, speaker, listener, inbox, settings, chat))
    try:
        gapp.run([])
    finally:
        speaker.stop()
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
