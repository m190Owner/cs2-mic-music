from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QWidget

from ..audio.sink import Sink


class DevicePicker(QWidget):
    """A label + dropdown showing every output device.

    Selected device is exposed as ``current_device_index`` (returns ``None``
    if the 'None' entry is selected).
    """

    def __init__(self, label: str, allow_none: bool = False, parent=None) -> None:
        super().__init__(parent)
        self._allow_none = allow_none
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel(label))
        self.combo = QComboBox()
        layout.addWidget(self.combo, 1)
        self.refresh()

    def refresh(self) -> None:
        prev_data = self.combo.currentData()
        self.combo.clear()
        if self._allow_none:
            self.combo.addItem("(disabled)", None)
        for idx, name, api in Sink.list_output_devices():
            self.combo.addItem(f"[{api}] {name}", idx)
        if prev_data is not None:
            i = self.combo.findData(prev_data)
            if i >= 0:
                self.combo.setCurrentIndex(i)

    def set_current_index(self, device_index: int | None) -> None:
        i = self.combo.findData(device_index)
        if i >= 0:
            self.combo.setCurrentIndex(i)

    def current_device_index(self) -> int | None:
        return self.combo.currentData()
