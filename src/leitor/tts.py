"""OpenAI text-to-speech as a stream of raw PCM bytes, with an on-disk cache.

Audio format: PCM 24 kHz, signed 16-bit little-endian, mono.
"""

import hashlib
import threading
from collections.abc import Iterator
from pathlib import Path

SAMPLE_RATE = 24_000


class Cancelled(Exception):
    pass


class SpeechCache:
    """Raw PCM files keyed by a hash of everything that affects the audio.

    Least-recently-used files are removed once the total exceeds max_bytes.
    """

    def __init__(self, directory: Path, max_bytes: int):
        self.directory = directory
        self.max_bytes = max_bytes

    @staticmethod
    def key(text: str, model: str, voice: str, instructions: str) -> str:
        raw = "\x1f".join([model, voice, instructions, text]).encode()
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
    """Turns text into PCM byte chunks, from cache or streamed from OpenAI."""

    def __init__(self, client, cache: SpeechCache):
        self.client = client  # openai.OpenAI (or a fake with the same shape)
        self.cache = cache

    def stream(
        self,
        text: str,
        *,
        model: str,
        voice: str,
        instructions: str,
        cancel: threading.Event | None = None,
    ) -> Iterator[bytes]:
        key = self.cache.key(text, model, voice, instructions)
        cached = self.cache.get(key)
        if cached is not None:
            yield cached
            return

        received = bytearray()
        with self.client.audio.speech.with_streaming_response.create(
            model=model,
            voice=voice,
            input=text,
            instructions=instructions,
            response_format="pcm",
        ) as response:
            for chunk in response.iter_bytes(chunk_size=4800):
                if cancel is not None and cancel.is_set():
                    raise Cancelled
                received += chunk
                yield chunk
        if received:
            self.cache.put(key, bytes(received))
