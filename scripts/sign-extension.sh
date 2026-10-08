#!/usr/bin/env bash
# Sign the Firefox extension on addons.mozilla.org as "unlisted" (private,
# self-distributed) and put the signed .xpi in web-ext-artifacts/.
#
# Needs AMO API credentials (https://addons.mozilla.org/developers/addon/api/key/)
# in WEB_EXT_API_KEY / WEB_EXT_API_SECRET. JWT_firefox_issuer / JWT_firefox_secret
# are accepted as aliases.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export WEB_EXT_API_KEY="${WEB_EXT_API_KEY:-${JWT_firefox_issuer:-}}"
export WEB_EXT_API_SECRET="${WEB_EXT_API_SECRET:-${JWT_firefox_secret:-}}"
[[ -n "$WEB_EXT_API_KEY" && -n "$WEB_EXT_API_SECRET" ]] || {
  echo "Defina WEB_EXT_API_KEY e WEB_EXT_API_SECRET (credenciais da API do AMO)." >&2; exit 1; }

source "$ROOT/scripts/_web-ext.sh"
web_ext sign --channel=unlisted --source-dir "$ROOT/extension" \
  --artifacts-dir "$ROOT/web-ext-artifacts" --approval-timeout 900000
ls -1 "$ROOT"/web-ext-artifacts/*.xpi
