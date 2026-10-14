import threading
from contextlib import contextmanager
from types import SimpleNamespace

import httpx2
import numpy as np
import pytest

from leitor import player
from leitor.audio import PcmQueue, float_to_pcm
from leitor.player import ReadJob, Segment, Voice, is_transient
from leitor.tts import SpeechCache, Synthesizer


class AuthenticationError(Exception):  # stands in for openai.AuthenticationError
    pass


def pcm(value, n=4):
    return float_to_pcm(np.full(n, value, np.float32))


class ScriptedClient:
    """Each API call plays the next script entry: a list of byte chunks and/or
    exceptions (raised when reached, like a connection dying mid-stream)."""

    def __init__(self, *script):
        self.script = list(script)
        self.calls = 0

        @contextmanager
        def create(**kwargs):
            self.calls += 1
            items = self.script.pop(0) if self.script else []

            def iter_bytes(chunk_size=None):
                for item in items:
                    if isinstance(item, Exception):
                        raise item
                    yield item

            if items and isinstance(items[0], Exception) and not isinstance(
                items[0], httpx2.TransportError
            ):
                raise items[0]  # fails before the response starts
            yield SimpleNamespace(iter_bytes=iter_bytes)

        self.audio = SimpleNamespace(
            speech=SimpleNamespace(with_streaming_response=SimpleNamespace(create=create)))


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch):
    monkeypatch.setattr(player, "retry_delay", lambda attempt: 0)


def run_job(tmp_path, client, text="Uma frase só."):
    queue, errors, reconnecting = PcmQueue(), [], []
    synth = Synthesizer(client, SpeechCache(tmp_path, 10**8))
    job = ReadJob([Segment("s", text)], synth, Voice("m", "v", ""), queue,
                  errors.append, reconnecting.append)
    job.start()
    job.join(timeout=5)
    assert not job.is_alive()
    return queue, errors, reconnecting


def test_redoes_chunk_after_mid_stream_drop(tmp_path):
    client = ScriptedClient(
        [pcm(0.25), httpx2.RemoteProtocolError("peer closed connection")],
        [pcm(0.5), pcm(0.5)],
    )
    queue, errors, reconnecting = run_job(tmp_path, client)
    assert client.calls == 2
    assert errors == []
    assert reconnecting == [True, False]
    # The unplayed part of the failed attempt is dropped; only the redo plays.
    samples = np.concatenate([a for _, a in queue.pop(100)])
    assert len(samples) == 8
    np.testing.assert_allclose(samples, 0.5, atol=1e-4)
    assert queue.drained


def test_keeps_retrying_until_network_is_back(tmp_path):
    down = [httpx2.ConnectError("Network is unreachable")]
    stalled = [pcm(0.25), httpx2.ReadTimeout("timed out")]
    client = ScriptedClient(down, down, stalled, down, [pcm(0.5)])
    queue, errors, reconnecting = run_job(tmp_path, client)
    assert client.calls == 5
    assert errors == []
    assert reconnecting == [True, False]
    assert [len(a) for _, a in queue.pop(100)] == [4]


def test_fatal_error_is_not_retried(tmp_path):
    client = ScriptedClient([AuthenticationError("bad key")], [pcm(0.5)])
    queue, errors, reconnecting = run_job(tmp_path, client)
    assert client.calls == 1
    assert errors == ["Chave da OpenAI inválida ou ausente (OPENAI_API_KEY)."]
    assert reconnecting == []
    assert queue.drained


def test_cancel_interrupts_retry_wait(tmp_path, monkeypatch):
    monkeypatch.setattr(player, "retry_delay", lambda attempt: 60)
    client = ScriptedClient([httpx2.ConnectError("down")])
    errors, reconnecting = [], []
    synth = Synthesizer(client, SpeechCache(tmp_path, 10**8))
    job = ReadJob([Segment("s", "Texto.")], synth, Voice("m", "v", ""), PcmQueue(),
                  errors.append, reconnecting.append)
    job.start()
    for _ in range(100):
        if reconnecting:
            break
        threading.Event().wait(0.01)
    job.cancel()
    job.join(timeout=2)
    assert not job.is_alive()
    assert errors == []


def test_transient_classification():
    class APIConnectionError(Exception): ...
    class APITimeoutError(APIConnectionError): ...
    class InternalServerError(Exception): ...
    class RateLimitError(Exception): ...

    for exc in (httpx2.RemoteProtocolError("x"), httpx2.ReadTimeout("x"),
                APITimeoutError(), InternalServerError(), ConnectionResetError()):
        assert is_transient(exc), exc
    for exc in (AuthenticationError(), RateLimitError(), ValueError()):
        assert not is_transient(exc), exc
