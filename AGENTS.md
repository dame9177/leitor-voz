# leitor-voz

Leitor de voz para estudo: extensão Firefox + app desktop que lê trechos em voz alta com Gemini TTS

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

- The Gemini key (`GEMINI_API_KEY`) lives only in the daemon. The extension talks to 127.0.0.1 through its
  background script; the server rejects any request with a web-page `Origin`, a non-loopback
  `Host`, or a non-JSON POST. Keep it that way (tests in `tests/test_server.py`).
- `.tools/` holds project-local Node 24 + web-ext + the dev Firefox profile (gitignored).
- System deps (installed 2026-10-08 with sudo): `libxcb-cursor0` (Qt 6 xcb plugin). `xclip` was already present.
- Code/comments in English; UI strings and docs in pt-BR.

## Status / next steps

- Workflow: the repo has outside users. Changes go through a branch + PR, never straight to
  `master`. Release = bump `pyproject.toml` version (+ `uv lock`), tag, then `gh release create`
  with notes and the `.xpi`. Re-sign the extension only if `extension/` changed, and bump its
  manifest version first. Releases: v0.1.0 (2026-10-08, OpenAI TTS), v0.3.0 (2026-10-14, Gemini;
  v0.2.0 was never released).
- User's machine: autostart and menu entries installed (`scripts/install-autostart.sh`,
  `LEITOR_ENV_FILE` = root `.env`). GNOME shortcut (`scripts/install-shortcut.sh`) not installed.
  Logs: `journalctl --user -t leitor-voz.desktop` (or `-u leitor-voz` if started by `systemd-run`).

### Decisions

- TTS provider is Gemini (`gemini-3.8-flash-tts`). OpenAI was dropped on 2026-10-14 because its
  stream stalled server-side (connection open, no bytes for 13 s+) while the network was fine.
  `tts.GeminiClient` calls the Interactions API over REST (`httpx2`, no SDK) with `stream: true`
  and `audio/l16` 24 kHz, parsing SSE `step.delta` audio events. Events seen on the real API:
  `interaction.created`, `interaction.status_update`, `step.start`, `step.delta` (~3 per 0.2 s of
  audio), `step.stop`, `interaction.completed`, `[DONE]`.
- Gemini reads the text verbatim and detects the language, so delivery goes in a short `style`
  (`speech_metadata`); long style prompts make the voice drift. `Settings.load` replaces v0.1
  OpenAI voice/model values with the Gemini defaults.
- Errors: 401/403 → `AuthError`, 402/429 → `QuotaError` (fatal; 402 = AI Studio prepaid credits
  ran out), 5xx and mid-stream error events → `ServerError` (retried).
- Resilience: `ReadJob._synthesize` retries a chunk on transient errors (`is_transient`, matched by
  class name) until cancelled: first retry immediate, then 1→10 s backoff. It drops the failed
  attempt's unplayed audio (`PcmQueue.drop_chunk`) and redoes the chunk from its start (the API
  can't resume mid-audio). Status has `reconnecting`. Fatal errors let queued audio play before
  showing the error. Retries and errors are logged to stderr.
- Stall timeout `tts.STALL_TIMEOUT` = 8 s. Measured: TTFB 1.8–2.9 s on ~850-char chunks, stream
  ≈4× real time, largest gap between events 0.41 s.
- Speed is applied locally with WSOLA (`audiotsm`) and bypassed at exactly 1.0×, because WSOLA at
  1.0 is not bit-exact. Synthesis runs at most 30 s ahead of playback, to limit wasted API spend.
- Hover detection widens a flex/grid row item to its row (≤4 children), so a "B)" + text
  alternative is read as one block. The rAF throttle was replaced by a timer: rAF doesn't fire in
  hidden tabs.
- Audio output: the format sets `ChannelConfigMono` explicitly (without it PipeWire sees an
  unpositioned `AUX0` channel and plays it only on the left). The sink is recreated when
  `QMediaDevices.audioOutputsChanged` fires and checked on every new reading. `outputs.py`
  (Qt-free): automatic mode prefers the most recently connected output, or the latest
  system-default change, else the system default (WirePlumber doesn't switch to a never-selected
  BT headset). A manual `output_device` wins while connected.

### Testing tricks

- End to end without the network: run the daemon with `LEITOR_GEMINI_URL` pointing to a fake SSE
  server, `QT_QPA_PLATFORM=offscreen` and `XDG_CONFIG_HOME`/`XDG_CACHE_HOME` in a temp dir (its
  `config.json` sets another `port`).
- Output switching without hardware: create a virtual sink with
  `pw-cli create-node adapter '{ factory.name=support.null-audio-sink node.name=x media.class=Audio/Sink audio.position=[FL FR] object.linger=true }'`.

### Ideas, not done

- Per-site tuning for Medway's DOM if the heuristics miss; "repeat last" shortcut.
