#!/usr/bin/env bash
# GNOME keyboard shortcut that reads the current selection in any app (X11).
# Usage: ./scripts/install-shortcut.sh ['<Control><Alt>l']
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BINDING="${1:-<Control><Alt>l}"
SCHEMA=org.gnome.settings-daemon.plugins.media-keys
PATH_KEY=/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/leitor-voz/
CUSTOM="$SCHEMA.custom-keybinding:$PATH_KEY"

current=$(gsettings get $SCHEMA custom-keybindings)
if [[ "$current" != *"$PATH_KEY"* ]]; then
  if [[ "$current" == "@as []" || "$current" == "[]" ]]; then
    new="['$PATH_KEY']"
  else
    new="${current%]}, '$PATH_KEY']"
  fi
  gsettings set $SCHEMA custom-keybindings "$new"
fi
gsettings set "$CUSTOM" name "Leitor de voz: ler seleção"
gsettings set "$CUSTOM" command "$ROOT/.venv/bin/leitor ler-selecao"
gsettings set "$CUSTOM" binding "$BINDING"
echo "Atalho $BINDING → leitor ler-selecao"
