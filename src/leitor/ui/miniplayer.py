"""Small floating player that appears while reading. Never steals focus."""

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from ..config import VOICES

SPEEDS = [0.75, 1.0, 1.15, 1.25, 1.5, 1.75, 2.0]

STYLE = """
#card { background: #1f2a27; border-radius: 12px; border: 1px solid #35463f; }
QLabel { color: #e9efe9; }
QLabel#title { font-weight: 600; }
QLabel#text { color: #b9c7bf; }
QLabel#error { color: #ff9b8f; }
QPushButton { background: #2f6f5e; color: white; border: none; border-radius: 8px;
              padding: 4px 10px; min-width: 28px; font-size: 14px; }
QPushButton:hover { background: #3a8571; }
QPushButton#close { background: transparent; color: #8fa39a; min-width: 18px; padding: 0 4px; }
QComboBox { background: #2a3733; color: #e9efe9; border: 1px solid #3c4e47;
            border-radius: 6px; padding: 2px 6px; }
"""

STATE_TITLES = {
    "loading": "Preparando a voz…",
    "playing": "Lendo",
    "paused": "Pausado",
    "idle": "Pronto",
    "error": "Erro",
}


class MiniPlayer(QWidget):
    action = Signal(str)            # pause/resume/toggle/stop/next
    settings_requested = Signal(dict)

    def __init__(self):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("Leitor de voz")
        self.setStyleSheet(STYLE)
        self._drag: QPoint | None = None
        self._placed = False

        card = QFrame(objectName="card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(card)

        self.title = QLabel(objectName="title")
        self.counter = QLabel()
        close = QPushButton("×", objectName="close")
        close.setToolTip("Esconder (a leitura continua)")
        close.clicked.connect(self.hide)
        top = QHBoxLayout()
        top.addWidget(self.title)
        top.addStretch()
        top.addWidget(self.counter)
        top.addWidget(close)

        self.text = QLabel(objectName="text")
        self.text.setWordWrap(True)
        self.text.setFixedWidth(300)
        self.error = QLabel(objectName="error")
        self.error.setWordWrap(True)
        self.error.setFixedWidth(300)
        self.error.hide()

        self.play = QPushButton("⏸")
        self.play.setToolTip("Pausar / retomar")
        self.play.clicked.connect(lambda: self.action.emit("toggle"))
        skip = QPushButton("⏭")
        skip.setToolTip("Pular para o próximo trecho")
        skip.clicked.connect(lambda: self.action.emit("next"))
        stop = QPushButton("⏹")
        stop.setToolTip("Parar")
        stop.clicked.connect(lambda: self.action.emit("stop"))

        self.speed = QComboBox()
        for s in SPEEDS:
            self.speed.addItem(f"{s:g}×", s)
        self.speed.setToolTip("Velocidade")
        self.speed.activated.connect(
            lambda: self.settings_requested.emit({"speed": self.speed.currentData()}))
        self.voice = QComboBox()
        self.voice.addItems(VOICES)
        self.voice.setToolTip("Voz (vale a partir da próxima leitura)")
        self.voice.activated.connect(
            lambda: self.settings_requested.emit({"voice": self.voice.currentText()}))

        controls = QHBoxLayout()
        for w in (self.play, skip, stop):
            controls.addWidget(w)
        controls.addStretch()
        controls.addWidget(self.speed)
        controls.addWidget(self.voice)

        footer = QLabel("Voz gerada por IA (OpenAI)")
        footer.setStyleSheet("color: #6f8279; font-size: 10px;")

        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 8)
        layout.addLayout(top)
        layout.addWidget(self.text)
        layout.addWidget(self.error)
        layout.addLayout(controls)
        layout.addWidget(footer)

        self._hide_timer = QTimer(self, singleShot=True, interval=4000)
        self._hide_timer.timeout.connect(self._auto_hide)

    # -- updates from the app --

    def show_settings(self, voice: str, speed: float) -> None:
        self.voice.setCurrentText(voice)
        i = self.speed.findData(speed)
        if i < 0:
            self.speed.addItem(f"{speed:g}×", speed)
            i = self.speed.count() - 1
        self.speed.setCurrentIndex(i)

    def show_status(self, status: dict) -> None:
        state = status["state"]
        self.title.setText(STATE_TITLES.get(state, state))
        self.play.setText("▶" if state == "paused" else "⏸")
        count = status.get("segment_count") or 0
        self.counter.setText(f"{status['segment_index'] + 1}/{count}" if count > 1 else "")
        text = status.get("text") or ""
        self.text.setText(text[:160] + ("…" if len(text) > 160 else ""))
        self.text.setVisible(bool(text))
        self.error.setText(status.get("error") or "")
        self.error.setVisible(state == "error")

        if state in ("loading", "playing", "paused", "error"):
            self._hide_timer.stop()
            self.popup()
        elif state == "idle":
            self._hide_timer.start()
        self.adjustSize()

    def popup(self) -> None:
        if not self._placed:
            self.adjustSize()
            area = QGuiApplication.primaryScreen().availableGeometry()
            self.move(area.right() - self.width() - 24, area.bottom() - self.height() - 24)
            self._placed = True
        self.show()

    def _auto_hide(self) -> None:
        if not self.underMouse():
            self.hide()

    # -- drag to move --

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self._drag is not None:
            self.move(event.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, event):
        self._drag = None
