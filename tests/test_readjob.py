import threading

import httpx2
import numpy as np
import pytest

from leitor import player
from leitor.audio import PcmQueue, float_to_pcm
from leitor.player import ReadJob, Segment, Voice, describe_error, is_transient, retry_delay
from leitor.tts import AuthError, QuotaError, ServerError, SpeechCache, Synthesizer


def pcm(value, n=4):
    return float_to_pcm(np.full(n, value, np.float32))


class ScriptedClient:
    """Each API call plays the next script entry: a list of byte chunks and/or
    exceptions (raised when reached, like a connection dying mid-stream)."""

    def __init__(self, *script):
        self.script = list(script)
        self.calls = 0

    def stream(self, text, **kwargs):
        self.calls += 1
        for item in self.script.pop(0) if self.script else []:
            if isinstance(item, Exception):
                raise item
            yield item


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
    client = ScriptedClient([AuthError("HTTP 401: bad key")], [pcm(0.5)])
    queue, errors, reconnecting = run_job(tmp_path, client)
    assert client.calls == 1
    assert errors == ["Chave do Gemini inválida ou ausente (GEMINI_API_KEY)."]
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


def test_server_error_is_retried(tmp_path):
    client = ScriptedClient([ServerError("HTTP 503: overloaded")], [pcm(0.5)])
    queue, errors, reconnecting = run_job(tmp_path, client)
    assert client.calls == 2
    assert errors == []
    assert reconnecting == [True, False]


def test_transient_classification():
    for exc in (httpx2.RemoteProtocolError("x"), httpx2.ReadTimeout("x"),
                httpx2.ConnectError("x"), ServerError("x"), ConnectionResetError()):
        assert is_transient(exc), exc
    for exc in (AuthError("x"), QuotaError("x"), ValueError()):
        assert not is_transient(exc), exc


def test_first_retry_is_immediate():
    assert [retry_delay(a) for a in range(6)] == [0, 1, 2, 4, 8, 10]


def test_quota_error_message():
    assert "Google AI Studio" in describe_error(QuotaError("HTTP 402: credits depleted"))
