#!/usr/bin/env bash
# Open a separate Firefox profile with the extension loaded (auto-reloads on edits).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/scripts/_web-ext.sh"
FIREFOX="$(command -v firefox)"
[[ -x /snap/bin/firefox ]] && FIREFOX=/snap/bin/firefox
mkdir -p "$ROOT/.tools/ff-profile"   # snap Firefox can't use /tmp profiles
web_ext run --source-dir "$ROOT/extension" --firefox="$FIREFOX" \
  --firefox-profile="$ROOT/.tools/ff-profile" --profile-create-if-missing --keep-profile-changes \
  --start-url "file://$ROOT/tests/pagina_exemplo.html" "$@"
