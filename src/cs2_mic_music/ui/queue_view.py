from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QListWidget, QListWidgetItem

from ..types import Track


class QueueView(QListWidget):
    play_requested = Signal(int)
    remove_requested = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.itemDoubleClicked.connect(self._on_double_click)
        self.setSelectionMode(QListWidget.SelectionMode.SingleSelection)

    def set_tracks(self, tracks: list[Track], current_index: int) -> None:
        self.clear()
        for i, t in enumerate(tracks):
            prefix = "▶ " if i == current_index else "  "
            mins = ""
            if t.duration_s:
                m, s = divmod(int(t.duration_s), 60)
                mins = f"  [{m}:{s:02d}]"
            kind_tag = "YT" if t.kind == "youtube" else "  "
            item = QListWidgetItem(f"{prefix}{kind_tag}  {t.display()}{mins}")
            item.setData(Qt.ItemDataRole.UserRole, i)
            self.addItem(item)

    def _on_double_click(self, item: QListWidgetItem) -> None:
        idx = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(idx, int):
            self.play_requested.emit(idx)

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if event.key() == Qt.Key.Key_Delete:
            row = self.currentRow()
            if row >= 0:
                self.remove_requested.emit(row)
                return
        super().keyPressEvent(event)
