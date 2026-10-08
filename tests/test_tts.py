import os
import threading
import time
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from leitor.tts import Cancelled, SpeechCache, Synthesizer


class FakeResponse:
    def __init__(self, chunks):
        self.chunks = chunks

    def iter_bytes(self, chunk_size=None):
        yield from self.chunks


class FakeClient:
    def __init__(self, chunks):
        self.calls = []
        self.chunks = chunks

        @contextmanager
        def create(**kwargs):
            self.calls.append(kwargs)
            yield FakeResponse(self.chunks)

        streaming = SimpleNamespace(create=create)
        speech = SimpleNamespace(with_streaming_response=streaming)
        self.audio = SimpleNamespace(speech=speech)


OPTS = dict(model="gpt-4o-mini-tts", voice="marin", instructions="calmo")


def test_streams_and_caches(tmp_path):
    client = FakeClient([b"ab", b"cd"])
    synth = Synthesizer(client, SpeechCache(tmp_path, 10_000))

    assert list(synth.stream("olá", **OPTS)) == [b"ab", b"cd"]
    assert client.calls[0]["response_format"] == "pcm"
    assert client.calls[0]["input"] == "olá"

    # Second time comes from the cache, without calling the API.
    assert list(synth.stream("olá", **OPTS)) == [b"abcd"]
    assert len(client.calls) == 1


def test_cache_key_depends_on_voice(tmp_path):
    client = FakeClient([b"ab"])
    synth = Synthesizer(client, SpeechCache(tmp_path, 10_000))
    list(synth.stream("olá", **OPTS))
    list(synth.stream("olá", **{**OPTS, "voice": "cedar"}))
    assert len(client.calls) == 2


def test_cancel_stops_and_does_not_cache(tmp_path):
    client = FakeClient([b"ab", b"cd"])
    synth = Synthesizer(client, SpeechCache(tmp_path, 10_000))
    cancel = threading.Event()
    stream = synth.stream("olá", **OPTS, cancel=cancel)
    cancel.set()
    with pytest.raises(Cancelled):
        next(stream)
    assert not list(tmp_path.glob("*.pcm"))


def test_lru_prune_removes_oldest(tmp_path):
    cache = SpeechCache(tmp_path, max_bytes=25)
    cache.put("old", b"x" * 10)
    cache.put("mid", b"x" * 10)
    past = time.time() - 100
    os.utime(tmp_path / "old.pcm", (past, past))
    cache.get("mid")  # touch
    cache.put("new", b"x" * 10)  # total 30 > 25 → drop oldest
    assert cache.get("old") is None
    assert cache.get("mid") is not None
    assert cache.get("new") is not None
