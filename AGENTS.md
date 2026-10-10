# leitor-voz

Leitor de voz para estudo: extensão Firefox + app desktop que lê trechos em voz alta com OpenAI TTS

Created 2026-10-08. Workspace-level rules live in `../AGENTS.md`. User-facing docs: `README.md`.
Public repo: https://github.com/dame9177/leitor-voz (MIT).

## Setup / run / test

```bash
uv sync
uv run pytest                         # chunker, cache, audio queue/stretch, HTTP server
LEITOR_ENV_FILE=../.env uv run leitor # daemon (tray + mini-player + API on 127.0.0.1:47321)
./scripts/dev-firefox.sh              # separate Firefox profile with the extension (auto-reload)
```

- Extension lint: `.tools/node/bin/node .tools/node_modules/.bin/web-ext lint --source-dir extension`.
- Content-script logic without Firefox: serve the repo (`python3 -m http.server 8765`) and open
  `tests/extension_harness.html` (fakes the `browser` API, logs requests in `window.__requests`).
- Sign: `./scripts/sign-extension.sh` (unlisted on AMO) → `web-ext-artifacts/*.xpi`. Bump
  `version` in `extension/manifest.json` first; AMO rejects re-used versions.
  Credentials: `JWT_firefox_issuer` / `JWT_firefox_secret` in the root `.env` (aliases of
  `WEB_EXT_API_KEY` / `WEB_EXT_API_SECRET`).

## Project rules

- The OpenAI key lives only in the daemon. The extension talks to 127.0.0.1 through its
  background script; the server rejects any request with a web-page `Origin`, a non-loopback
  `Host`, or a non-JSON POST. Keep it that way (tests in `tests/test_server.py`).
- `.tools/` holds project-local Node 24 + web-ext + the dev Firefox profile (gitignored).
- System deps (installed 2026-10-08 with sudo): `libxcb-cursor0` (Qt 6 xcb plugin). `xclip` was already present.
- Code/comments in English; UI strings and docs in pt-BR.

## Status / next steps

- Workflow since v0.2.0 (2026-10-10): the repo has outside users. Changes go through a branch + PR,
  never straight to `master`. Release = bump `pyproject.toml` version (+ `uv lock`), tag, then
  `gh release create` with notes and the `.xpi`. Re-sign the extension only if `extension/` changed,
  and bump its manifest version when you do.

- 2026-10-08: v0.1.0 working end-to-end and tested by the user in Firefox (hover 🔊, selection
  bubble, context menu, shortcuts, highlight). Signed unlisted XPI built. Autostart installed
  (`~/.config/autostart/leitor-voz.desktop`, uses `LEITOR_ENV_FILE` = root `.env`).
  GNOME shortcut (`scripts/install-shortcut.sh`) was offered but not installed.
- Decisions:
  - Speed is applied locally with WSOLA (`audiotsm`) and bypassed at exactly 1.0×, because
    WSOLA at 1.0 is not bit-exact.
  - Synthesis runs at most 30 s ahead of playback, to limit wasted API spend.
  - Hover detection widens a flex/grid row item to its row (≤4 children), so a "B)" + text
    alternative is read as one block.
  - The `requestAnimationFrame` throttle was replaced by a timer: rAF doesn't fire in hidden tabs.
- Audio follows the system default output: the sink is recreated when `QMediaDevices.audioOutputsChanged`
    fires (Bluetooth headphones) and checked on every new reading; `/status` reports `output`.
    Fixed 2026-10-08: the sink used to be bound to the startup default forever.
- The audio format sets `ChannelConfigMono` explicitly. Without it PipeWire sees an unpositioned
    `AUX0` channel and links it only to the left side (fixed 2026-10-08, `tests/test_player_format.py`).
- Output selection (`outputs.py`, Qt-free, tested): automatic mode prefers the most recently
    connected output, or the latest system-default change, else the system default. WirePlumber does
    not switch the default to a never-selected BT headset, which is why this exists. A manual
    choice (`output_device`) wins while connected. To test without hardware, create a virtual sink:
    `pw-cli create-node adapter '{ factory.name=support.null-audio-sink node.name=x media.class=Audio/Sink audio.position=[FL FR] object.linger=true }'`.
- Ideas, not done: per-site tuning for Medway's DOM if the heuristics miss; "repeat last" shortcut.
