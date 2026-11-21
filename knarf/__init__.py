"""knarf: a little circle that talks and listens.

Speaks text with Piper while a transparent, borderless circle animates with the voice,
and turns speech into text with faster-whisper, typed into the focused window.
It runs all the time with a tray icon; `talk` (bin/talk) drives it over local HTTP.

Modules:
    config    paths, constants, the persistent Settings
    speaker   text-to-speech worker (Piper + pw-play)
    listener  speech-to-text worker (arecord + faster-whisper)
    server    the local HTTP API and the events it shares with the UI
    gtk       GTK4 imports (borrowed from the system's python3-gi)
    sway      small sway IPC helpers
    style     colours and CSS
    tray      the tray icon (StatusNotifierItem + dbusmenu)
    window    the circle window (Circle)
    panel     the settings window
"""
