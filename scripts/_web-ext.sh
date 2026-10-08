# Shared helper: run web-ext from .tools/ (project-local Node), or a global one.
_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
web_ext() {
  if [[ -x "$_root/.tools/node_modules/.bin/web-ext" ]]; then
    PATH="$_root/.tools/node/bin:$PATH" "$_root/.tools/node_modules/.bin/web-ext" "$@"
  elif command -v web-ext >/dev/null; then
    command web-ext "$@"
  else
    npx --yes web-ext "$@"
  fi
}
