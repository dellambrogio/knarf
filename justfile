# knarf — a little window that talks and listens.

piper_dir := env("HOME") / ".local/share/piper"
venv      := piper_dir / "venv"
bin_dir   := env("HOME") / ".local/bin"
apps_dir  := env("HOME") / ".local/share/applications"
voice     := "en_US-lessac-medium"
voice_url := "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium"
sway_cfg  := env("HOME") / ".config/sway/config"
unit_dir  := env("HOME") / ".config/systemd/user"

# list recipes
default:
    @just --list

# full install: dependencies, voice, commands, desktop launcher and the always-on service
install: deps voice link desktop service
    @echo "installed. start with: knarf &   speak with: talk \"hello\"   listen with: talk --listen"

# Python venv with piper-tts and faster-whisper (reuses the existing Piper venv)
deps:
    test -x {{venv}}/bin/python || python3 -m venv {{venv}}
    {{venv}}/bin/pip install -q piper-tts faster-whisper numpy
    @for c in pw-play arecord wtype curl; do command -v $c >/dev/null || echo "warning: $c not found"; done
    @{{venv}}/bin/python -c 'import sys; sys.path.append("/usr/lib/python3/dist-packages"); import gi, cairo; gi.require_version("Gtk", "4.0")' 2>/dev/null \
        || echo "warning: GTK4 bindings missing: sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0"

# download the Piper voice if missing
voice:
    mkdir -p {{piper_dir}}
    test -f {{piper_dir}}/{{voice}}.onnx || curl -fL -o {{piper_dir}}/{{voice}}.onnx {{voice_url}}/{{voice}}.onnx
    test -f {{piper_dir}}/{{voice}}.onnx.json || curl -fL -o {{piper_dir}}/{{voice}}.onnx.json {{voice_url}}/{{voice}}.onnx.json

# link knarf and talk into ~/.local/bin
link:
    mkdir -p {{bin_dir}}
    ln -sf {{justfile_directory()}}/bin/knarf {{bin_dir}}/knarf
    ln -sf {{justfile_directory()}}/bin/talk {{bin_dir}}/talk

# add the app-launcher entry
desktop:
    mkdir -p {{apps_dir}}
    printf '%s\n' '[Desktop Entry]' 'Type=Application' 'Name=knarf' 'Comment=A little window that talks' \
        'Exec={{justfile_directory()}}/bin/knarf' 'Icon=audio-speakers' 'Terminal=false' \
        'Categories=AudioVideo;Utility;' > {{apps_dir}}/knarf.desktop

# run knarf all the time as a systemd user service (tray icon; restarts if it crashes)
service:
    mkdir -p {{unit_dir}}
    printf '%s\n' \
        '[Unit]' \
        'Description=knarf: talking circle with a tray icon (text-to-speech, speech-to-text)' \
        'StartLimitIntervalSec=0' \
        '' \
        '[Service]' \
        'ExecStart={{justfile_directory()}}/bin/knarf' \
        '# fails until sway has exported WAYLAND_DISPLAY to systemd at login, then starts' \
        'Restart=on-failure' \
        'RestartSec=5' \
        '' \
        '[Install]' \
        'WantedBy=default.target' > {{unit_dir}}/knarf.service
    systemctl --user daemon-reload
    systemctl --user enable --now knarf.service

# restart the service (after changing the code)
restart:
    systemctl --user restart knarf.service

# follow knarf's log
logs:
    journalctl --user -u knarf.service -f

# bind Super+\ to push-to-talk in sway (idempotent) and reload sway
sway-bind:
    grep -q 'talk --listen' {{sway_cfg}} || printf '\n# knarf: push-to-talk (speak, then it types into the focused window)\nbindsym $mod+backslash exec {{bin_dir}}/talk --listen\n' >> {{sway_cfg}}
    swaymsg reload >/dev/null

# remove service, commands, launcher and sway binding (keeps Piper, models and settings)
uninstall:
    -systemctl --user disable --now knarf.service
    rm -f {{unit_dir}}/knarf.service
    -systemctl --user daemon-reload
    rm -f {{bin_dir}}/knarf {{bin_dir}}/talk {{apps_dir}}/knarf.desktop
    sed -i '/# knarf: push-to-talk/d; /talk --listen/d' {{sway_cfg}} 2>/dev/null || true
    -swaymsg reload >/dev/null 2>&1

# start the window
run:
    {{justfile_directory()}}/bin/knarf

# say something through the running window
say *text:
    {{justfile_directory()}}/bin/talk {{quote(text)}}
