from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QPushButton, QWidget


class UrlBox(QWidget):
    submitted = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("Paste YouTube URL, playlist, or search query…")
        self.btn = QPushButton("Add")
        layout.addWidget(self.edit, 1)
        layout.addWidget(self.btn)
        self.btn.clicked.connect(self._emit)
        self.edit.returnPressed.connect(self._emit)

    def _emit(self) -> None:
        txt = self.edit.text().strip()
        if txt:
            self.submitted.emit(txt)
            self.edit.clear()
