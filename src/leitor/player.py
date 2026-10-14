"""Reading jobs (synthesis in a background thread) and playback with QAudioSink."""

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtMultimedia import QAudio, QAudioFormat, QAudioSink, QMediaDevices

from .audio import PcmQueue, Stretcher, float_to_pcm
from .chunker import split_text
from .outputs import OutputChooser
from .tts import SAMPLE_RATE, AuthError, Cancelled, QuotaError, Synthesizer, TtsError

log = logging.getLogger(__name__)

MAX_AHEAD_SECONDS = 30  # don't synthesize (and pay for) far beyond what is playing
SINK_BUFFER_SECONDS = 0.3
RETRY_MAX_DELAY = 10.0

# Trouble worth waiting out. Matched by class name (anywhere in the MRO) so this module
# doesn't import httpx: server errors (5xx or mid-stream), httpx connection errors and
# stalls (read timeout), and plain socket errors.
TRANSIENT_ERRORS = {"ServerError", "TransportError", "ConnectionError", "TimeoutError"}


def is_transient(exc: Exception) -> bool:
    return any(cls.__name__ in TRANSIENT_ERRORS for cls in type(exc).__mro__)


def retry_delay(attempt: int) -> float:
    """Seconds to wait before retry number attempt+1: 0, 1, 2, 4, 8, 10, 10…

    The first retry is immediate: a stalled stream is usually the server, not the network.
    """
    return 0.0 if attempt == 0 else min(2.0 ** (attempt - 1), RETRY_MAX_DELAY)


@dataclass
class Segment:
    id: str
    text: str


@dataclass
class Voice:
    model: str
    voice: str
    style: str


class ReadJob(threading.Thread):
    """Synthesizes segments in order, pushing PCM into the queue.

    A chunk that fails on network trouble is retried until it succeeds or the job is
    cancelled; on_reconnecting(True/False) brackets the wait. Other errors end the job.
    """

    def __init__(
        self,
        segments: list[Segment],
        synth: Synthesizer,
        voice: Voice,
        queue: PcmQueue,
        on_error: Callable[[str], None],
        on_reconnecting: Callable[[bool], None],
    ):
        super().__init__(daemon=True)
        self.segments = segments
        self.synth = synth
        self.voice = voice
        self.queue = queue
        self.on_error = on_error
        self.on_reconnecting = on_reconnecting
        self.cancelled = threading.Event()
        self._skip: set[str] = set()
        self._chunk = 0

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
                    self._synthesize(seg.id, chunk)
        except Cancelled:
            pass
        except Exception as exc:  # network, auth, quota… surface to the UI
            if not self.cancelled.is_set():
                log.error("reading stopped: %s: %s", type(exc).__name__, exc)
                self.on_error(describe_error(exc))
        finally:
            self.queue.finish()

    def _synthesize(self, segment_id: str, text: str) -> None:
        self._chunk += 1
        attempt = 0
        try:
            while True:
                try:
                    for data in self.synth.stream(
                        text,
                        model=self.voice.model,
                        voice=self.voice.voice,
                        style=self.voice.style,
                        cancel=self.cancelled,
                    ):
                        if segment_id in self._skip:
                            return
                        self.queue.push(segment_id, data, self._chunk)
                    return
                except Exception as exc:
                    if self.cancelled.is_set() or not is_transient(exc):
                        raise
                    log.warning("chunk %d, attempt %d failed: %s: %s",
                                self._chunk, attempt + 1, type(exc).__name__, exc)
                # The API can't resume mid-audio, so the chunk is redone from its start.
                # Dropping its unplayed audio means only what was already heard repeats.
                self.queue.drop_chunk(self._chunk)
                if attempt == 0:
                    self.on_reconnecting(True)
                if self.cancelled.wait(retry_delay(attempt)):
                    raise Cancelled
                attempt += 1
                if segment_id in self._skip:
                    return
        finally:
            if attempt:
                log.info("chunk %d recovered after %d failed attempts", self._chunk, attempt)
                self.on_reconnecting(False)


def describe_error(exc: Exception) -> str:
    if isinstance(exc, AuthError):
        return "Chave do Gemini inválida ou ausente (GEMINI_API_KEY)."
    if isinstance(exc, QuotaError):
        return ("Créditos ou limite do Gemini esgotados. "
                "Verifique o faturamento do projeto no Google AI Studio.")
    if isinstance(exc, TtsError):
        return f"Erro do Gemini: {exc}"
    return f"{type(exc).__name__}: {exc}"


def device_id(device) -> str:
    return bytes(device.id()).decode(errors="replace")


def list_outputs() -> list[tuple[str, str]]:
    """(id, description) of every audio output, for menus."""
    return [(device_id(d), d.description()) for d in QMediaDevices.audioOutputs()]


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
    outputs_changed = Signal()
    _job_error = Signal(str)
    _job_reconnecting = Signal(object, bool)  # (job, flag)

    def __init__(self, synth: Synthesizer, speed: Callable[[], float], manual_output: str = ""):
        super().__init__()
        self.synth = synth
        self.speed = speed  # read live, so speed changes apply mid-reading

        self.format = audio_format()
        self.sink: QAudioSink | None = None
        self.device_id = None
        self.device_name = ""
        self.io = None
        self.manual_output = manual_output  # "" = automatic
        self.chooser = OutputChooser(
            [i for i, _ in list_outputs()], device_id(QMediaDevices.defaultAudioOutput()))
        self._ensure_sink()
        # Follow device changes (e.g. Bluetooth headphones connected later).
        self.devices = QMediaDevices(self)
        self.devices.audioOutputsChanged.connect(self._on_outputs_changed)

        self.timer = QTimer(self)
        self.timer.setInterval(20)
        self.timer.timeout.connect(self._tick)
        self._job_error.connect(self._on_job_error)
        self._job_reconnecting.connect(self._on_job_reconnecting)

        self.job: ReadJob | None = None
        self.error: str | None = None  # shown once the audio already received has played
        self.queue = PcmQueue()
        self.stretcher = Stretcher()
        self.pending = b""
        self.flushed = False
        self.segments: list[Segment] = []
        self.status = {
            "state": "idle", "reading_id": None, "segment_id": None,
            "segment_index": 0, "segment_count": 0, "text": "", "error": None,
            "reconnecting": False,
        }

    # -- public API ----------------------------------------------------------

    def read(self, reading_id: str, segments: list[Segment], voice: Voice) -> None:
        self._halt()
        self.segments = segments
        self.queue = PcmQueue()
        self.stretcher = Stretcher()
        self.pending = b""
        self.flushed = False
        self.error = None
        job = ReadJob(segments, self.synth, voice, self.queue, self._job_error.emit,
                      lambda flag: self._job_reconnecting.emit(job, flag))
        self.job = job
        job.start()
        self._ensure_sink()
        self.io = self.sink.start()
        self._set(state="loading", reading_id=reading_id, error=None, reconnecting=False,
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
        self._set(state="idle", segment_id=None, text="", reconnecting=False)

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

    def set_manual_output(self, output_id: str) -> None:
        """Use this device whenever it is connected; "" means automatic."""
        self.manual_output = output_id
        self._switch_if_needed()

    # -- internals -------------------------------------------------------------

    def _target_device(self):
        wanted = self.chooser.choose(self.manual_output)
        for device in QMediaDevices.audioOutputs():
            if device_id(device) == wanted:
                return device
        return QMediaDevices.defaultAudioOutput()

    def _ensure_sink(self) -> bool:
        """(Re)create the sink if the target output device changed. True if recreated."""
        device = self._target_device()
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
        self.chooser.update(
            [i for i, _ in list_outputs()], device_id(QMediaDevices.defaultAudioOutput()))
        self._switch_if_needed()
        self.outputs_changed.emit()

    def _switch_if_needed(self) -> None:
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
        # The job has stopped; let the audio already queued play out, then show the error.
        self.error = message

    def _on_job_reconnecting(self, job: ReadJob, flag: bool) -> None:
        if job is self.job:
            self._set(reconnecting=flag)

    def _finish(self) -> None:
        if self.error is None:
            self.stop()
        else:
            self._halt()
            self._set(state="error", error=self.error, reconnecting=False)

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
                self._finish()
