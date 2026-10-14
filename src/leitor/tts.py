"""Gemini text-to-speech as a stream of raw PCM bytes, with an on-disk cache.

Audio format: PCM 24 kHz, signed 16-bit little-endian, mono.
"""

import base64
import hashlib
import json
import threading
from collections.abc import Iterator
from pathlib import Path

import httpx2

SAMPLE_RATE = 24_000
API_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"

# The server sends audio several times faster than real time; this long without a byte
# means the stream stalled. ReadJob then redoes the chunk instead of staying silent.
STALL_TIMEOUT = 8.0


class Cancelled(Exception):
    pass


class TtsError(Exception):
    """The API refused the request; the message is the one the server gave."""


class AuthError(TtsError):
    pass


class QuotaError(TtsError):
    """No credits left (402) or rate limited (429)."""


class ServerError(TtsError):
    """5xx or an error event mid-stream: worth retrying."""


def error_for(status: int, body: bytes) -> TtsError:
    try:
        message = json.loads(body)
        if isinstance(message, list):
            message = message[0]
        message = message["error"]["message"]
    except (ValueError, LookupError, TypeError):
        message = body[:300].decode(errors="replace")
    message = f"HTTP {status}: {message}".strip()
    if status in (401, 403):
        return AuthError(message)
    if status in (402, 429):
        return QuotaError(message)
    if status >= 500:
        return ServerError(message)
    return TtsError(message)


class GeminiClient:
    """Streams single-speaker speech from the Gemini Interactions API."""

    def __init__(self, api_key: str, url: str = API_URL, http: httpx2.Client | None = None):
        self.api_key = api_key
        self.url = url
        self.http = http or httpx2.Client(
            timeout=httpx2.Timeout(60.0, connect=10.0, read=STALL_TIMEOUT))

    def stream(self, text: str, *, model: str, voice: str, style: str) -> Iterator[bytes]:
        part = {"type": "text", "text": text}
        if style:
            part["annotations"] = [{"type": "speech_metadata", "style": style}]
        body = {
            "model": model,
            "input": [{"type": "user_input", "content": [part]}],
            "response_format": {"type": "audio", "mime_type": "audio/l16",
                                "sample_rate": SAMPLE_RATE},
            "generation_config": {"speech_config": [{"voice": voice}]},
            "stream": True,
        }
        headers = {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}
        with self.http.stream("POST", self.url, headers=headers, json=body) as response:
            if response.status_code != 200:
                raise error_for(response.status_code, response.read())
            for line in response.iter_lines():
                audio = parse_event(line)
                if audio:
                    yield audio


def parse_event(line: str) -> bytes | None:
    """PCM carried by one server-sent-event line, if any."""
    if not line.startswith("data:"):
        return None
    payload = line[5:].strip()
    if not payload or payload == "[DONE]":
        return None
    event = json.loads(payload)
    if "error" in event:
        error = event["error"]
        raise ServerError(error.get("message", str(error)) if isinstance(error, dict) else error)
    delta = event.get("delta") or {}
    if event.get("event_type") == "step.delta" and delta.get("type") == "audio":
        return base64.b64decode(delta.get("data", ""))
    return None


class SpeechCache:
    """Raw PCM files keyed by a hash of everything that affects the audio.

    Least-recently-used files are removed once the total exceeds max_bytes.
    """

    def __init__(self, directory: Path, max_bytes: int):
        self.directory = directory
        self.max_bytes = max_bytes

    @staticmethod
    def key(text: str, model: str, voice: str, style: str) -> str:
        raw = "\x1f".join([model, voice, style, text]).encode()
        return hashlib.sha256(raw).hexdigest()

    def _path(self, key: str) -> Path:
        return self.directory / f"{key}.pcm"

    def get(self, key: str) -> bytes | None:
        path = self._path(key)
        try:
            data = path.read_bytes()
        except OSError:
            return None
        path.touch()  # mark as recently used
        return data

    def put(self, key: str, data: bytes) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        tmp = self._path(key).with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(self._path(key))
        self.prune()

    def prune(self) -> None:
        files = [(p.stat(), p) for p in self.directory.glob("*.pcm")]
        total = sum(st.st_size for st, _ in files)
        for st, path in sorted(files, key=lambda item: item[0].st_mtime):
            if total <= self.max_bytes:
                break
            path.unlink(missing_ok=True)
            total -= st.st_size


class Synthesizer:
    """Turns text into PCM byte chunks, from cache or streamed from the API."""

    def __init__(self, client, cache: SpeechCache):
        self.client = client  # GeminiClient (or a fake with the same stream())
        self.cache = cache

    def stream(
        self,
        text: str,
        *,
        model: str,
        voice: str,
        style: str,
        cancel: threading.Event | None = None,
    ) -> Iterator[bytes]:
        key = self.cache.key(text, model, voice, style)
        cached = self.cache.get(key)
        if cached is not None:
            yield cached
            return

        received = bytearray()
        for chunk in self.client.stream(text, model=model, voice=voice, style=style):
            if cancel is not None and cancel.is_set():
                raise Cancelled
            received += chunk
            yield chunk
        if received:
            self.cache.put(key, bytes(received))
