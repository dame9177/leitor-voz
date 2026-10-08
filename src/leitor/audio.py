"""Qt-free audio plumbing: a thread-safe PCM queue tagged by segment, and a
streaming time-stretcher (WSOLA) that is bypassed at 1.0x."""

import threading
from collections import deque

import numpy as np
from audiotsm import wsola
from audiotsm.io.array import ArrayReader, ArrayWriter

from .tts import SAMPLE_RATE


def pcm_to_float(data: bytes) -> np.ndarray:
    return np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0


def float_to_pcm(samples: np.ndarray) -> bytes:
    return (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()


class PcmQueue:
    """Producer pushes PCM bytes for a segment; consumer pops float samples."""

    def __init__(self):
        self._items: deque[tuple[str, np.ndarray]] = deque()
        self._carry = b""  # odd trailing byte between network chunks
        self._lock = threading.Lock()
        self._finished = False

    def push(self, segment_id: str, data: bytes) -> None:
        with self._lock:
            data = self._carry + data
            cut = len(data) - (len(data) % 2)
            self._carry = data[cut:]
            if cut:
                self._items.append((segment_id, pcm_to_float(data[:cut])))

    def finish(self) -> None:
        with self._lock:
            self._finished = True

    def buffered_seconds(self) -> float:
        with self._lock:
            return sum(len(a) for _, a in self._items) / SAMPLE_RATE

    def pop(self, n: int) -> list[tuple[str, np.ndarray]]:
        out = []
        with self._lock:
            while n > 0 and self._items:
                seg, arr = self._items[0]
                if len(arr) <= n:
                    self._items.popleft()
                    out.append((seg, arr))
                    n -= len(arr)
                else:
                    out.append((seg, arr[:n]))
                    self._items[0] = (seg, arr[n:])
                    n = 0
        return out

    def drop_segment(self, segment_id: str) -> None:
        with self._lock:
            self._items = deque(i for i in self._items if i[0] != segment_id)

    @property
    def drained(self) -> bool:
        with self._lock:
            return self._finished and not self._items


class Stretcher:
    """Streaming tempo change without pitch change. Exact passthrough at 1.0x."""

    def __init__(self):
        self._tsm = None
        self._speed = 1.0

    def _flush(self) -> np.ndarray:
        if self._tsm is None:
            return np.zeros(0, dtype=np.float32)
        writer = ArrayWriter(1)
        self._tsm.flush_to(writer)
        self._tsm = None
        return writer.data[0]

    def process(self, samples: np.ndarray, speed: float) -> np.ndarray:
        head = np.zeros(0, dtype=np.float32)
        if speed != self._speed:
            if speed == 1.0:
                head = self._flush()
            elif self._tsm is None:
                self._tsm = wsola(1, speed=speed)
            else:
                self._tsm.set_speed(speed)
            self._speed = speed
        if self._tsm is None:
            return np.concatenate([head, samples]) if len(head) else samples
        reader, writer = ArrayReader(samples[None, :]), ArrayWriter(1)
        while not reader.empty:
            self._tsm.read_from(reader)
            self._tsm.write_to(writer)
        self._tsm.write_to(writer)
        return np.concatenate([head, writer.data[0]])

    def finish(self) -> np.ndarray:
        tail = self._flush()
        self._speed = 1.0
        return tail

    def reset(self) -> None:
        self._tsm = None
        self._speed = 1.0
