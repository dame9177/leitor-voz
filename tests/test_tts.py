import base64
import json
import os
import threading
import time

import httpx2
import pytest

from leitor.tts import (
    AuthError, Cancelled, GeminiClient, QuotaError, ServerError, SpeechCache, Synthesizer,
)


class FakeClient:
    def __init__(self, chunks):
        self.calls = []
        self.chunks = chunks

    def stream(self, text, **kwargs):
        self.calls.append({"text": text, **kwargs})
        yield from self.chunks


OPTS = dict(model="gemini-3.8-flash-tts", voice="Kore", style="calmo")


def test_streams_and_caches(tmp_path):
    client = FakeClient([b"ab", b"cd"])
    synth = Synthesizer(client, SpeechCache(tmp_path, 10_000))

    assert list(synth.stream("olá", **OPTS)) == [b"ab", b"cd"]
    assert client.calls[0] == {"text": "olá", **OPTS}

    # Second time comes from the cache, without calling the API.
    assert list(synth.stream("olá", **OPTS)) == [b"abcd"]
    assert len(client.calls) == 1


def test_cache_key_depends_on_voice(tmp_path):
    client = FakeClient([b"ab"])
    synth = Synthesizer(client, SpeechCache(tmp_path, 10_000))
    list(synth.stream("olá", **OPTS))
    list(synth.stream("olá", **{**OPTS, "voice": "Puck"}))
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


# -- GeminiClient against a mocked HTTP transport -------------------------------------


def sse(*events):
    return "".join(f"data: {json.dumps(e)}\n\n" for e in events).encode()


def audio_event(data: bytes):
    return {"event_type": "step.delta",
            "delta": {"type": "audio", "data": base64.b64encode(data).decode()}}


def gemini(handler):
    requests = []

    def record(request):
        requests.append(request)
        return handler(request)

    http = httpx2.Client(transport=httpx2.MockTransport(record))
    return GeminiClient("k3y", url="https://tts.test/v1beta/interactions", http=http), requests


def test_gemini_request_and_audio_events():
    body = sse(
        {"event_type": "interaction.start"},
        audio_event(b"\x01\x02"),
        {"event_type": "step.delta", "delta": {"type": "text", "text": "ignored"}},
        audio_event(b"\x03\x04"),
        {"event_type": "interaction.complete"},
    ) + b"data: [DONE]\n\n"
    client, requests = gemini(lambda r: httpx2.Response(
        200, content=body, headers={"content-type": "text/event-stream"}))

    chunks = list(client.stream("Olá, mundo.", model="m", voice="Kore", style="calmo"))

    assert chunks == [b"\x01\x02", b"\x03\x04"]
    req = requests[0]
    assert req.headers["x-goog-api-key"] == "k3y"
    sent = json.loads(req.content)
    assert sent["model"] == "m"
    assert sent["stream"] is True
    assert sent["response_format"] == {"type": "audio", "mime_type": "audio/l16",
                                       "sample_rate": 24000}
    assert sent["generation_config"] == {"speech_config": [{"voice": "Kore"}]}
    part = sent["input"][0]["content"][0]
    assert part["text"] == "Olá, mundo."
    assert part["annotations"] == [{"type": "speech_metadata", "style": "calmo"}]


def test_gemini_omits_empty_style():
    client, requests = gemini(lambda r: httpx2.Response(200, content=b""))
    list(client.stream("Oi.", model="m", voice="Kore", style=""))
    assert "annotations" not in json.loads(requests[0].content)["input"][0]["content"][0]


@pytest.mark.parametrize("status,error", [
    (401, AuthError), (403, AuthError), (402, QuotaError), (429, QuotaError),
    (500, ServerError), (503, ServerError),
])
def test_gemini_http_errors(status, error):
    body = json.dumps([{"error": {"code": status, "message": "credits depleted"}}]).encode()
    client, _ = gemini(lambda r: httpx2.Response(status, content=body))
    with pytest.raises(error, match="credits depleted"):
        list(client.stream("Oi.", model="m", voice="Kore", style=""))


def test_gemini_error_event_mid_stream_is_retryable():
    body = sse(audio_event(b"\x01\x02"), {"error": {"message": "overloaded"}})
    client, _ = gemini(lambda r: httpx2.Response(200, content=body))
    stream = client.stream("Oi.", model="m", voice="Kore", style="")
    assert next(stream) == b"\x01\x02"
    with pytest.raises(ServerError, match="overloaded"):
        next(stream)
