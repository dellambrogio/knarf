# knarf — a little window that talks and listens.

piper_dir := env("HOME") / ".local/share/piper"
venv      := piper_dir / "venv"
bin_dir   := env("HOME") / ".local/bin"
apps_dir  := env("HOME") / ".local/share/applications"
voice     := "en_US-lessac-medium"
voice_url := "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium"
sway_cfg  := env("HOME") / ".config/sway/config"

# list recipes
default:
    @just --list

# full install: dependencies, voice, commands and desktop launcher
install: deps voice link desktop
    @echo "installed. start with: knarf &   speak with: talk \"hello\"   listen with: talk --listen"

# Python venv with piper-tts and faster-whisper (reuses the existing Piper venv)
deps:
    test -x {{venv}}/bin/python || python3 -m venv {{venv}}
    {{venv}}/bin/pip install -q piper-tts faster-whisper numpy
    @for c in pw-play arecord wtype curl; do command -v $c >/dev/null || echo "warning: $c not found"; done

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

# bind Super+\ to push-to-talk in sway (idempotent) and reload sway
sway-bind:
    grep -q 'talk --listen' {{sway_cfg}} || printf '\n# knarf: push-to-talk (speak, then it types into the focused window)\nbindsym $mod+backslash exec {{bin_dir}}/talk --listen\n' >> {{sway_cfg}}
    swaymsg reload >/dev/null

# remove commands, launcher and sway binding (keeps Piper, models and settings)
uninstall:
    rm -f {{bin_dir}}/knarf {{bin_dir}}/talk {{apps_dir}}/knarf.desktop
    sed -i '/# knarf: push-to-talk/d; /talk --listen/d' {{sway_cfg}} 2>/dev/null || true
    -swaymsg reload >/dev/null 2>&1

# start the window
run:
    {{justfile_directory()}}/bin/knarf

# say something through the running window
say *text:
    {{justfile_directory()}}/bin/talk {{quote(text)}}
