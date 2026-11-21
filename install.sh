#!/usr/bin/env bash
# Link knarf + talk into ~/.local/bin and add a desktop launcher.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p ~/.local/bin ~/.local/share/applications
ln -sf "$HERE/bin/knarf" ~/.local/bin/knarf
ln -sf "$HERE/bin/talk"  ~/.local/bin/talk
cat > ~/.local/share/applications/knarf.desktop <<DESK
[Desktop Entry]
Type=Application
Name=knarf
Comment=A little window that talks
Exec=$HERE/bin/knarf
Icon=audio-speakers
Terminal=false
Categories=AudioVideo;Utility;
DESK
echo "installed: knarf, talk -> ~/.local/bin; launcher -> ~/.local/share/applications/knarf.desktop"
