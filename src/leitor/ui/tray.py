"""Top-bar icon with the main menu."""

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction, QActionGroup, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from ..config import VOICES
from .miniplayer import SPEEDS


class Tray(QObject):
    action = Signal(str)            # read_selection/toggle/stop/show/quit
    settings_requested = Signal(dict)

    def __init__(self, icon: QIcon):
        super().__init__()
        self.icon = QSystemTrayIcon(icon)
        self.icon.setToolTip("Leitor de voz — voz gerada por IA (OpenAI)")
        menu = QMenu()

        def add(label, name):
            act = menu.addAction(label)
            act.triggered.connect(lambda: self.action.emit(name))
            return act

        add("Ler seleção", "read_selection")
        add("Pausar / retomar", "toggle")
        add("Parar", "stop")
        menu.addSeparator()

        self.voice_actions = self._radio_menu(
            menu.addMenu("Voz"), VOICES, lambda v: {"voice": v}, str)
        self.speed_actions = self._radio_menu(
            menu.addMenu("Velocidade"), SPEEDS, lambda s: {"speed": s}, lambda s: f"{s:g}×")
        self.output_menu = menu.addMenu("Saída de áudio")

        menu.addSeparator()
        add("Mostrar player", "show")
        add("Sair", "quit")
        self.menu = menu  # keep a reference
        self.icon.setContextMenu(menu)
        self.icon.activated.connect(self._activated)

    def _radio_menu(self, submenu: QMenu, values, payload, label) -> dict:
        group = QActionGroup(submenu)
        actions = {}
        for value in values:
            act = QAction(label(value), submenu, checkable=True)
            act.triggered.connect(lambda _=False, v=value: self.settings_requested.emit(payload(v)))
            group.addAction(act)
            submenu.addAction(act)
            actions[value] = act
        return actions

    def _activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.action.emit("show")

    def show_settings(self, voice: str, speed: float) -> None:
        if voice in self.voice_actions:
            self.voice_actions[voice].setChecked(True)
        if speed in self.speed_actions:
            self.speed_actions[speed].setChecked(True)

    def show_outputs(self, outputs: list[tuple[str, str]], manual: str, current: str) -> None:
        self.output_menu.clear()
        group = QActionGroup(self.output_menu)
        auto_label = f"Automático ({current})" if not manual else "Automático"
        for output_id, label in [("", auto_label), *outputs]:
            act = QAction(label, self.output_menu, checkable=True)
            act.setChecked(output_id == manual)
            act.triggered.connect(
                lambda _=False, v=output_id: self.settings_requested.emit({"output_device": v}))
            group.addAction(act)
            self.output_menu.addAction(act)

    def notify(self, title: str, message: str) -> None:
        self.icon.showMessage(title, message, QSystemTrayIcon.MessageIcon.Warning, 6000)

    def show(self) -> None:
        self.icon.show()
