"""Which audio output to use. Qt-free so it can be tested.

Automatic mode follows the most recent "intent" signal:
- a device that just connected (e.g. Bluetooth headphones), or
- a change of the system default output (the user picked it in GNOME).
If the preferred device is gone, it falls back to the system default.
A manual choice wins whenever that device is connected.
"""


class OutputChooser:
    def __init__(self, device_ids: list[str], default_id: str):
        self._present = list(device_ids)
        self._default = default_id
        self._preferred: str | None = None

    def update(self, device_ids: list[str], default_id: str) -> None:
        appeared = [d for d in device_ids if d not in self._present]
        if appeared:
            self._preferred = appeared[-1]
        if default_id != self._default and default_id not in appeared:
            self._preferred = default_id
        self._present = list(device_ids)
        self._default = default_id

    def choose(self, manual: str = "") -> str:
        if manual and manual in self._present:
            return manual
        if self._preferred and self._preferred in self._present:
            return self._preferred
        return self._default
