#!/usr/bin/env bash
# Start the Leitor de voz app at login and add it to the applications menu.
# Writes ~/.config/autostart/leitor-voz.desktop and
# ~/.local/share/applications/leitor-voz.desktop (user-level, no sudo).
#
# Optional: LEITOR_ENV_FILE=/path/to/.env ./scripts/install-autostart.sh
# makes the app load OPENAI_API_KEY from that file (default: ~/.config/leitor-voz/.env).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN="$ROOT/.venv/bin/leitor"
ICON="$ROOT/src/leitor/assets/icon.svg"
[[ -x "$BIN" ]] || { echo "Rode 'uv sync' em $ROOT primeiro." >&2; exit 1; }

EXEC="$BIN"
if [[ -n "${LEITOR_ENV_FILE:-}" ]]; then
  EXEC="env LEITOR_ENV_FILE=$(realpath "$LEITOR_ENV_FILE") $BIN"
fi

entry() {
  cat <<DESKTOP
[Desktop Entry]
Type=Application
Name=Leitor de voz
Comment=Lê em voz alta trechos selecionados (OpenAI TTS)
Exec=$EXEC
Icon=$ICON
Terminal=false
Categories=Utility;Accessibility;
X-GNOME-Autostart-enabled=true
DESKTOP
}

mkdir -p ~/.config/autostart ~/.local/share/applications
entry > ~/.config/autostart/leitor-voz.desktop
entry > ~/.local/share/applications/leitor-voz.desktop
echo "Autostart: ~/.config/autostart/leitor-voz.desktop"
echo "Menu:      ~/.local/share/applications/leitor-voz.desktop"
