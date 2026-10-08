"""The desktop daemon: wires settings, synthesis, playback, HTTP API and UI."""

import copy
import os
import sys
import threading
import uuid
from importlib.resources import files

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .config import VOICES, Settings, cache_dir, load_env
from .player import Player, Segment, Voice
from .selection import read_primary_selection
from .server import ApiServer
from .tts import SpeechCache, Synthesizer
from .ui.miniplayer import MiniPlayer
from .ui.tray import Tray


class App(QObject):
    """Thread-safe facade for the HTTP server; UI lives on the main thread."""

    _read_requested = Signal(str, list)
    _control_requested = Signal(str)
    _settings_changed = Signal()

    def __init__(self, settings: Settings, synth: Synthesizer):
        super().__init__()
        self.settings = settings
        self._lock = threading.Lock()
        self.player = Player(synth, speed=lambda: self.settings.speed)
        self._player_status = dict(self.player.status)

        icon = QIcon(str(files("leitor") / "assets" / "icon.svg"))
        QApplication.setWindowIcon(icon)
        self.mini = MiniPlayer()
        self.tray = Tray(icon)

        self._read_requested.connect(self._do_read)
        self._control_requested.connect(self._do_control)
        self._settings_changed.connect(self._show_settings)
        self.player.status_changed.connect(self._on_status)
        self.mini.action.connect(self._do_control)
        self.mini.settings_requested.connect(self._update_from_ui)
        self.tray.action.connect(self._do_control)
        self.tray.settings_requested.connect(self._update_from_ui)

        self._show_settings()
        self.tray.show()

    # -- Controller protocol (any thread) -------------------------------------

    def read(self, segments: list[dict]) -> str:
        reading_id = uuid.uuid4().hex[:10]
        self._read_requested.emit(reading_id, segments)
        return reading_id

    def control(self, action: str) -> None:
        self._control_requested.emit(action)

    def update_settings(self, data: dict) -> dict:
        with self._lock:
            candidate = copy.copy(self.settings)
            candidate.update(data)  # raises ValueError on bad input
            self.settings.update(data)
            self.settings.save()
        self._settings_changed.emit()
        return self._settings_view()

    def status(self) -> dict:
        return {**self._player_status, **self._settings_view(), "output": self.player.device_name}

    def _settings_view(self) -> dict:
        return {"voice": self.settings.voice, "speed": self.settings.speed, "voices": VOICES}

    # -- main thread ----------------------------------------------------------

    def _do_read(self, reading_id: str, segments: list) -> None:
        voice = Voice(self.settings.model, self.settings.voice, self.settings.instructions)
        self.player.read(reading_id, [Segment(s["id"], s["text"]) for s in segments], voice)

    def _do_control(self, action: str) -> None:
        if action == "read_selection":
            text = read_primary_selection()
            if text.strip():
                self._do_read(uuid.uuid4().hex[:10], [{"id": "0", "text": text}])
            else:
                self.tray.notify("Leitor de voz", "Nenhum texto selecionado.")
        elif action == "show":
            self.mini.show_status(self.player.status)
            self.mini.popup()
        elif action == "quit":
            self.player.stop()
            QApplication.quit()
        elif action in ("pause", "resume", "toggle", "stop", "next"):
            getattr(self.player, action)()

    def _update_from_ui(self, data: dict) -> None:
        try:
            self.update_settings(data)
        except ValueError as exc:
            self.tray.notify("Leitor de voz", str(exc))

    def _show_settings(self) -> None:
        self.mini.show_settings(self.settings.voice, self.settings.speed)
        self.tray.show_settings(self.settings.voice, self.settings.speed)

    def _on_status(self, status: dict) -> None:
        self._player_status = status
        self.mini.show_status(status)


def run_daemon() -> int:
    load_env()
    settings = Settings.load()
    qt = QApplication(sys.argv)
    qt.setApplicationName("leitor-voz")
    qt.setQuitOnLastWindowClosed(False)

    import openai  # slow import; keep it off the CLI path

    client = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY") or "ausente", max_retries=1)
    synth = Synthesizer(client, SpeechCache(cache_dir(), settings.cache_mb * 1024 * 1024))
    app = App(settings, synth)
    try:
        server = ApiServer(app, settings.port)
    except OSError:
        print(f"Porta {settings.port} ocupada: o leitor já está rodando?", file=sys.stderr)
        return 1
    server.start()
    if not os.environ.get("OPENAI_API_KEY"):
        app.tray.notify(
            "Leitor de voz",
            "OPENAI_API_KEY não encontrada. Defina no ambiente ou em ~/.config/leitor-voz/.env.",
        )
    print(f"Leitor de voz ouvindo em http://127.0.0.1:{server.port}", flush=True)
    code = qt.exec()
    server.close()
    return code
