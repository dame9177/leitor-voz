"""Reading jobs (synthesis in a background thread) and playback with QAudioSink."""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtMultimedia import QAudio, QAudioFormat, QAudioSink, QMediaDevices

from .audio import PcmQueue, Stretcher, float_to_pcm
from .chunker import split_text
from .tts import SAMPLE_RATE, Cancelled, Synthesizer

MAX_AHEAD_SECONDS = 30  # don't synthesize (and pay for) far beyond what is playing
SINK_BUFFER_SECONDS = 0.3


@dataclass
class Segment:
    id: str
    text: str


@dataclass
class Voice:
    model: str
    voice: str
    instructions: str


class ReadJob(threading.Thread):
    """Synthesizes segments in order, pushing PCM into the queue."""

    def __init__(
        self,
        segments: list[Segment],
        synth: Synthesizer,
        voice: Voice,
        queue: PcmQueue,
        on_error: Callable[[str], None],
    ):
        super().__init__(daemon=True)
        self.segments = segments
        self.synth = synth
        self.voice = voice
        self.queue = queue
        self.on_error = on_error
        self.cancelled = threading.Event()
        self._skip: set[str] = set()

    def cancel(self) -> None:
        self.cancelled.set()

    def skip(self, segment_id: str) -> None:
        self._skip.add(segment_id)

    def _wait_for_room(self) -> None:
        while self.queue.buffered_seconds() > MAX_AHEAD_SECONDS and not self.cancelled.is_set():
            time.sleep(0.1)

    def run(self) -> None:
        try:
            for seg in self.segments:
                for chunk in split_text(seg.text):
                    self._wait_for_room()
                    if self.cancelled.is_set():
                        return
                    if seg.id in self._skip:
                        break
                    for data in self.synth.stream(
                        chunk,
                        model=self.voice.model,
                        voice=self.voice.voice,
                        instructions=self.voice.instructions,
                        cancel=self.cancelled,
                    ):
                        if seg.id in self._skip:
                            break
                        self.queue.push(seg.id, data)
        except Cancelled:
            pass
        except Exception as exc:  # network, auth, quota… surface to the UI
            if not self.cancelled.is_set():
                self.on_error(describe_error(exc))
        finally:
            self.queue.finish()


def describe_error(exc: Exception) -> str:
    name = type(exc).__name__
    if name == "AuthenticationError":
        return "Chave da OpenAI inválida ou ausente (OPENAI_API_KEY)."
    if name == "RateLimitError":
        return "Limite/cota da OpenAI atingido (429). Verifique o saldo da conta."
    if name in ("APIConnectionError", "APITimeoutError"):
        return "Sem conexão com a OpenAI."
    return f"{name}: {exc}"


def audio_format() -> QAudioFormat:
    """24 kHz mono s16. The explicit mono channel config matters: without it
    PipeWire gets an unpositioned AUX0 channel and plays it on one side only."""
    fmt = QAudioFormat()
    fmt.setSampleRate(SAMPLE_RATE)
    fmt.setChannelCount(1)
    fmt.setChannelConfig(QAudioFormat.ChannelConfig.ChannelConfigMono)
    fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
    return fmt


class Player(QObject):
    """Plays one reading at a time. All methods must run on the Qt main thread."""

    status_changed = Signal(dict)
    _job_error = Signal(str)

    def __init__(self, synth: Synthesizer, speed: Callable[[], float]):
        super().__init__()
        self.synth = synth
        self.speed = speed  # read live, so speed changes apply mid-reading

        self.format = audio_format()
        self.sink: QAudioSink | None = None
        self.device_id = None
        self.device_name = ""
        self.io = None
        self._ensure_sink()
        # Follow the system default output (e.g. Bluetooth headphones connected later).
        self.devices = QMediaDevices(self)
        self.devices.audioOutputsChanged.connect(self._on_outputs_changed)

        self.timer = QTimer(self)
        self.timer.setInterval(20)
        self.timer.timeout.connect(self._tick)
        self._job_error.connect(self._on_job_error)

        self.job: ReadJob | None = None
        self.queue = PcmQueue()
        self.stretcher = Stretcher()
        self.pending = b""
        self.flushed = False
        self.segments: list[Segment] = []
        self.status = {
            "state": "idle", "reading_id": None, "segment_id": None,
            "segment_index": 0, "segment_count": 0, "text": "", "error": None,
        }

    # -- public API ----------------------------------------------------------

    def read(self, reading_id: str, segments: list[Segment], voice: Voice) -> None:
        self._halt()
        self.segments = segments
        self.queue = PcmQueue()
        self.stretcher = Stretcher()
        self.pending = b""
        self.flushed = False
        self.job = ReadJob(segments, self.synth, voice, self.queue, self._job_error.emit)
        self.job.start()
        self._ensure_sink()
        self.io = self.sink.start()
        self._set(state="loading", reading_id=reading_id, error=None,
                  segment_count=len(segments), **self._segment_fields(segments[0].id))
        self.timer.start()

    def pause(self) -> None:
        if self.status["state"] in ("playing", "loading"):
            self.sink.suspend()
            self._set(state="paused")

    def resume(self) -> None:
        if self.status["state"] == "paused":
            self.sink.resume()
            self._set(state="playing")

    def toggle(self) -> None:
        if self.status["state"] == "paused":
            self.resume()
        else:
            self.pause()

    def stop(self) -> None:
        self._halt()
        self._set(state="idle", segment_id=None, text="")

    def next(self) -> None:
        seg = self.status["segment_id"]
        if self.job is None or seg is None:
            return
        self.job.skip(seg)
        self.queue.drop_segment(seg)
        self.pending = b""
        self.stretcher.reset()
        self.sink.reset()  # drop what is still buffered in the device
        self.io = self.sink.start()
        if self.status["state"] == "paused":
            self._set(state="playing")

    # -- internals -------------------------------------------------------------

    def _ensure_sink(self) -> bool:
        """(Re)create the sink if the default output device changed. True if recreated."""
        device = QMediaDevices.defaultAudioOutput()
        if self.sink is not None and device.id() == self.device_id:
            return False
        if self.sink is not None:
            self.sink.stop()
            self.sink.deleteLater()
        self.sink = QAudioSink(device, self.format, self)
        self.sink.setBufferSize(int(SAMPLE_RATE * 2 * SINK_BUFFER_SECONDS))
        self.device_id = device.id()
        self.device_name = device.description()
        return True

    def _on_outputs_changed(self) -> None:
        playing = self.io is not None
        if not self._ensure_sink() or not playing:
            return
        # Move the ongoing reading to the new device (loses ~0.3 s already buffered).
        self.io = self.sink.start()
        if self.status["state"] == "paused":
            self.sink.suspend()

    def _segment_fields(self, segment_id: str) -> dict:
        for i, seg in enumerate(self.segments):
            if seg.id == segment_id:
                return {"segment_id": seg.id, "segment_index": i, "text": seg.text[:300]}
        return {"segment_id": segment_id}

    def _set(self, **changes) -> None:
        self.status = {**self.status, **changes}
        self.status_changed.emit(dict(self.status))

    def _halt(self) -> None:
        self.timer.stop()
        if self.job is not None:
            self.job.cancel()
            self.job = None
        self.sink.stop()
        self.io = None

    def _on_job_error(self, message: str) -> None:
        self._halt()
        self._set(state="error", error=message)

    def _write_pending(self) -> None:
        if self.pending and self.io is not None:
            free = self.sink.bytesFree()
            n = self.io.write(self.pending[: free - free % 2])
            if n > 0:
                self.pending = self.pending[n:]

    def _tick(self) -> None:
        if self.status["state"] == "paused" or self.io is None:
            return
        self._write_pending()
        if self.pending:
            return
        free = self.sink.bytesFree() // 2
        if free < SAMPLE_RATE // 50:
            return
        speed = self.speed()
        pieces = self.queue.pop(int(free * speed) + 1)
        if pieces:
            seg = pieces[-1][0]
            if seg != self.status["segment_id"]:
                self._set(**self._segment_fields(seg))
            samples = np.concatenate([arr for _, arr in pieces])
            self.pending += float_to_pcm(self.stretcher.process(samples, speed))
            self._write_pending()
            if self.status["state"] == "loading":
                self._set(state="playing")
        elif self.queue.drained:
            if not self.flushed:
                self.pending += float_to_pcm(self.stretcher.finish())
                self.flushed = True
                self._write_pending()
            elif self.sink.state() == QAudio.State.IdleState or (
                self.sink.bytesFree() >= self.sink.bufferSize()
            ):
                self.stop()
