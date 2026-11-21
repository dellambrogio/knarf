# knarf — a little window that talks and listens.

piper_dir := env("HOME") / ".local/share/piper"
venv      := piper_dir / "venv"
bin_dir   := env("HOME") / ".local/bin"
apps_dir  := env("HOME") / ".local/share/applications"
voice     := "en_US-lessac-medium"
sway_cfg  := env("HOME") / ".config/sway/config"
unit_dir  := env("HOME") / ".config/systemd/user"
pw_dir    := env("HOME") / ".config/pipewire/pipewire.conf.d"

# list recipes
default:
    @just --list

# full install: dependencies, voice, commands, desktop launcher, the always-on service, Claude's tools
install: deps voice link desktop service mcp
    @echo "installed. start with: knarf &   speak with: talk \"hello\"   listen with: talk --listen"

# Python venv with piper-tts and faster-whisper (reuses the existing Piper venv)
deps:
    test -x {{venv}}/bin/python || python3 -m venv {{venv}}
    {{venv}}/bin/pip install -q piper-tts faster-whisper numpy
    @for c in pw-play arecord wtype curl; do command -v $c >/dev/null || echo "warning: $c not found"; done
    @{{venv}}/bin/python -c 'import sys; sys.path.append("/usr/lib/python3/dist-packages"); import gi, cairo; gi.require_version("Gtk", "4.0")' 2>/dev/null \
        || echo "warning: GTK4 bindings missing: sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0"

# download a Piper voice if missing (name like en_GB-alan-medium; see https://huggingface.co/rhasspy/piper-voices)
voice name=voice:
    #!/usr/bin/env bash
    set -euo pipefail
    IFS=- read -r lang speaker quality <<< "{{name}}"
    url="https://huggingface.co/rhasspy/piper-voices/resolve/main/${lang%%_*}/$lang/$speaker/$quality/{{name}}"
    mkdir -p {{piper_dir}}
    for ext in onnx onnx.json; do
        f={{piper_dir}}/{{name}}.$ext
        test -f "$f" || { curl -fL -o "$f.part" "$url.$ext" && mv "$f.part" "$f"; }
    done

# download a selection of extra English voices (pick them in the settings window)
voices:
    for v in en_US-amy-medium en_US-ryan-high en_US-joe-medium en_US-hfc_female-medium \
             en_GB-alan-medium en_GB-jenny_dioco-medium en_GB-cori-high; do just voice $v; done

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

# give Claude Code knarf's tools (speak, listen, stop, status) in every project
mcp:
    -claude mcp remove --scope user knarf >/dev/null 2>&1
    claude mcp add --scope user knarf -- {{justfile_directory()}}/bin/knarf-mcp

# noise suppression for listening: adds the "knarf mic" to PipeWire (restarts PipeWire: audio stops a moment)
audio-setup:
    mkdir -p {{pw_dir}}
    cp {{justfile_directory()}}/pipewire/knarf-echo-cancel.conf {{pw_dir}}/
    systemctl --user restart pipewire pipewire-pulse wireplumber
    @sleep 2; pw-cli ls Node | grep -q '"knarf_mic"' && echo "knarf mic: on" || echo "knarf mic: off"

# take the knarf mic out of PipeWire again
audio-remove:
    rm -f {{pw_dir}}/knarf-echo-cancel.conf
    systemctl --user restart pipewire pipewire-pulse wireplumber

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
    -claude mcp remove --scope user knarf
    -systemctl --user disable --now knarf.service
    rm -f {{unit_dir}}/knarf.service
    -systemctl --user daemon-reload
    rm -f {{bin_dir}}/knarf {{bin_dir}}/talk {{apps_dir}}/knarf.desktop
    sed -i '/# knarf: push-to-talk/d; /talk --listen/d' {{sway_cfg}} 2>/dev/null || true
    -swaymsg reload >/dev/null 2>&1

# start the window
run:
    {{justfile_directory()}}/bin/knarf

# redraw docs/circle.png (the circle's four states) from the drawing code
screenshots:
    PYTHONPATH={{justfile_directory()}} {{venv}}/bin/python {{justfile_directory()}}/apps/screenshots.py

# make docs/demo.mp4 (with sound) and docs/demo.webp (silent preview for the README)
demo:
    PYTHONPATH={{justfile_directory()}} {{venv}}/bin/python {{justfile_directory()}}/apps/demo.py
    ffmpeg -loglevel error -y -i {{justfile_directory()}}/docs/demo.mp4 -vf "fps=15,scale=360:-1:flags=lanczos" \
        -c:v libwebp_anim -loop 0 -quality 70 -compression_level 6 {{justfile_directory()}}/docs/demo.webp

# say something through the running window
say *text:
    {{justfile_directory()}}/bin/talk {{quote(text)}}
