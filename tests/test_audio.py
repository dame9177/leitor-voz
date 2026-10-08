import numpy as np

from leitor.audio import PcmQueue, Stretcher, float_to_pcm, pcm_to_float


def tone(seconds, rate=24_000):
    t = np.arange(int(seconds * rate)) / rate
    return (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def test_queue_handles_odd_byte_boundaries():
    q = PcmQueue()
    data = float_to_pcm(np.linspace(-0.5, 0.5, 10, dtype=np.float32))
    q.push("a", data[:5])
    q.push("a", data[5:])
    popped = np.concatenate([arr for _, arr in q.pop(100)])
    np.testing.assert_allclose(popped, pcm_to_float(data))


def test_queue_pop_splits_items_and_keeps_segment_ids():
    q = PcmQueue()
    q.push("a", float_to_pcm(np.zeros(4, np.float32)))
    q.push("b", float_to_pcm(np.zeros(4, np.float32)))
    first = q.pop(6)
    assert [(s, len(a)) for s, a in first] == [("a", 4), ("b", 2)]
    assert [(s, len(a)) for s, a in q.pop(10)] == [("b", 2)]


def test_queue_drained_and_drop_segment():
    q = PcmQueue()
    q.push("a", float_to_pcm(np.zeros(4, np.float32)))
    q.push("b", float_to_pcm(np.zeros(4, np.float32)))
    q.finish()
    assert not q.drained
    q.drop_segment("a")
    assert [s for s, _ in q.pop(100)] == ["b"]
    assert q.drained


def test_stretcher_is_exact_passthrough_at_1x():
    s = Stretcher()
    x = tone(0.5)
    np.testing.assert_array_equal(s.process(x, 1.0), x)
    assert len(s.finish()) == 0


def test_stretcher_changes_duration_when_streaming():
    s = Stretcher()
    x = tone(3.0)
    out = [s.process(x[i : i + 2400], 1.5) for i in range(0, len(x), 2400)]
    out.append(s.finish())
    total = sum(len(o) for o in out)
    assert abs(total - len(x) / 1.5) < 2400  # within 0.1 s


def test_stretcher_switch_back_to_1x_flushes():
    s = Stretcher()
    x = tone(1.0)
    a = s.process(x, 1.5)
    b = s.process(x, 1.0)  # flushes the tsm tail, then passes through
    assert len(b) >= len(x)
    assert len(a) + len(b) > len(x) / 1.5 + len(x) - 2400
