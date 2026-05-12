from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSlider,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from ..config import Config
from ..player import playlists, youtube_resolver
from ..player.transport import Transport
from ..sources import local
from ..types import Track
from .device_picker import DevicePicker
from .queue_view import QueueView
from .url_box import UrlBox

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    # Hotkey signals - emitted from pynput callback threads, connected
    # via Qt::QueuedConnection so they run on the GUI thread.
    hk_play_pause = Signal()
    hk_next = Signal()
    hk_prev = Signal()
    hk_vol_up = Signal()
    hk_vol_down = Signal()

    def __init__(
        self,
        config: Config,
        transport: Transport,
        on_devices_changed,  # Callable[[int|None, int|None], None]
    ) -> None:
        super().__init__()
        self.config = config
        self.transport = transport
        self._on_devices_changed = on_devices_changed
        self.setWindowTitle("CS2 Mic Music")
        self.resize(900, 600)

        self._build_ui()
        self._wire()
        self._refresh_queue()

        # Status updates while playback advances.
        self._tick = QTimer(self)
        self._tick.setInterval(500)
        self._tick.timeout.connect(self._refresh_status)
        self._tick.start()

        self.transport.add_listener(self._refresh_queue)

    # --- UI construction --------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # Device row
        dev_row = QHBoxLayout()
        self.primary_picker = DevicePicker("Mic output (CS2):", allow_none=False)
        self.monitor_picker = DevicePicker("Monitor (headphones):", allow_none=True)
        self.monitor_check = QCheckBox("Hear it myself")
        self.monitor_check.setChecked(self.config.monitor_enabled)
        dev_row.addWidget(self.primary_picker, 2)
        dev_row.addWidget(self.monitor_picker, 2)
        dev_row.addWidget(self.monitor_check)
        root.addLayout(dev_row)

        if self.config.primary_device_index is not None:
            self.primary_picker.set_current_index(self.config.primary_device_index)
        if self.config.monitor_device_index is not None:
            self.monitor_picker.set_current_index(self.config.monitor_device_index)

        # Transport row
        ctl_row = QHBoxLayout()
        self.btn_prev = QPushButton("⏮")
        self.btn_play = QPushButton("▶")
        self.btn_next = QPushButton("⏭")
        self.btn_stop = QPushButton("⏹")
        for b in (self.btn_prev, self.btn_play, self.btn_next, self.btn_stop):
            b.setFixedWidth(48)
            ctl_row.addWidget(b)
        ctl_row.addSpacing(20)
        ctl_row.addWidget(QLabel("Volume"))
        self.vol_slider = QSlider(Qt.Orientation.Horizontal)
        self.vol_slider.setRange(0, 150)
        self.vol_slider.setValue(int(self.config.master_volume * 100))
        ctl_row.addWidget(self.vol_slider, 1)
        self.vol_label = QLabel(f"{int(self.config.master_volume * 100)}%")
        ctl_row.addWidget(self.vol_label)
        root.addLayout(ctl_row)

        # URL/search
        self.url_box = UrlBox()
        root.addWidget(self.url_box)

        # Library + Playlist buttons
        lib_row = QHBoxLayout()
        self.btn_add_folder = QPushButton("Add folder…")
        self.btn_add_files = QPushButton("Add files…")
        self.btn_save_pl = QPushButton("Save playlist…")
        self.btn_load_pl = QPushButton("Load playlist…")
        self.btn_clear = QPushButton("Clear queue")
        for b in (self.btn_add_folder, self.btn_add_files, self.btn_save_pl, self.btn_load_pl, self.btn_clear):
            lib_row.addWidget(b)
        lib_row.addStretch(1)
        root.addLayout(lib_row)

        # Queue
        self.queue_view = QueueView()
        root.addWidget(self.queue_view, 1)

        self.setStatusBar(QStatusBar())

    def _wire(self) -> None:
        # Devices
        self.primary_picker.combo.currentIndexChanged.connect(self._devices_changed)
        self.monitor_picker.combo.currentIndexChanged.connect(self._devices_changed)
        self.monitor_check.stateChanged.connect(self._devices_changed)

        # Transport buttons
        self.btn_play.clicked.connect(self.transport.pause_toggle)
        self.btn_play.clicked.connect(
            lambda: self.transport.play_current() if not self.transport.mixer.has_current else None
        )
        self.btn_next.clicked.connect(self.transport.next)
        self.btn_prev.clicked.connect(self.transport.prev)
        self.btn_stop.clicked.connect(self.transport.stop)

        self.vol_slider.valueChanged.connect(self._volume_changed)

        # Library + playlists
        self.btn_add_folder.clicked.connect(self._add_folder)
        self.btn_add_files.clicked.connect(self._add_files)
        self.btn_save_pl.clicked.connect(self._save_playlist)
        self.btn_load_pl.clicked.connect(self._load_playlist)
        self.btn_clear.clicked.connect(self._clear_queue)

        # URL
        self.url_box.submitted.connect(self._add_url)

        # Queue
        self.queue_view.play_requested.connect(self.transport.play_track_at)
        self.queue_view.remove_requested.connect(self._remove_track)

        # Hotkey signals (queued connection by default since the senders are
        # cross-thread Qt Signals).
        self.hk_play_pause.connect(self._hk_play_pause)
        self.hk_next.connect(self.transport.next)
        self.hk_prev.connect(self.transport.prev)
        self.hk_vol_up.connect(lambda: self._adjust_volume(5))
        self.hk_vol_down.connect(lambda: self._adjust_volume(-5))

    # --- handlers --------------------------------------------------------
    def _hk_play_pause(self) -> None:
        if self.transport.mixer.has_current:
            self.transport.pause_toggle()
        else:
            self.transport.play_current()

    def _devices_changed(self) -> None:
        primary = self.primary_picker.current_device_index()
        monitor = (
            self.monitor_picker.current_device_index()
            if self.monitor_check.isChecked()
            else None
        )
        self.config.primary_device_index = primary
        self.config.monitor_device_index = self.monitor_picker.current_device_index()
        self.config.monitor_enabled = self.monitor_check.isChecked()
        self.config.save()
        self._on_devices_changed(primary, monitor)

    def _volume_changed(self, value: int) -> None:
        v = value / 100.0
        self.transport.set_volume(v)
        self.config.master_volume = v
        self.vol_label.setText(f"{value}%")
        self.config.save()

    def _adjust_volume(self, delta_pct: int) -> None:
        new = max(0, min(150, self.vol_slider.value() + delta_pct))
        self.vol_slider.setValue(new)

    def _add_folder(self) -> None:
        start = self.config.last_library_folder or str(Path.home() / "Music")
        folder = QFileDialog.getExistingDirectory(self, "Pick music folder", start)
        if not folder:
            return
        self.config.last_library_folder = folder
        self.config.save()
        tracks = local.scan_folder(Path(folder))
        if not tracks:
            QMessageBox.information(self, "No audio", "No audio files found in that folder.")
            return
        self.transport.queue.add_many(tracks)
        self._refresh_queue()
        self.statusBar().showMessage(f"Added {len(tracks)} tracks", 4000)

    def _add_files(self) -> None:
        start = self.config.last_library_folder or str(Path.home() / "Music")
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Pick audio files",
            start,
            "Audio (*.mp3 *.flac *.wav *.m4a *.aac *.ogg *.opus);;All files (*)",
        )
        if not files:
            return
        tracks = [local.track_from_file(Path(f)) for f in files]
        self.transport.queue.add_many(tracks)
        self._refresh_queue()

    def _add_url(self, query: str) -> None:
        self.statusBar().showMessage(f"Resolving: {query}…", 0)

        def ok(tracks: list[Track]):
            self.transport.queue.add_many(tracks)
            self._refresh_queue()
            if len(tracks) == 1:
                self.statusBar().showMessage(f"Added: {tracks[0].display()}", 4000)
            else:
                self.statusBar().showMessage(
                    f"Added {len(tracks)} tracks from playlist", 4000
                )

        def err(msg: str):
            self.statusBar().showMessage("", 0)
            QMessageBox.warning(self, "Failed", f"Could not resolve:\n{msg}")

        youtube_resolver.resolve_async(query, ok, err)

    def _save_playlist(self) -> None:
        name, ok = QInputDialog.getText(self, "Save playlist", "Name:")
        if not ok or not name.strip():
            return
        path = playlists.save(name.strip(), self.transport.queue.tracks)
        self.statusBar().showMessage(f"Saved {path.name}", 4000)

    def _load_playlist(self) -> None:
        names = playlists.list_all()
        if not names:
            QMessageBox.information(self, "No playlists", "No saved playlists yet.")
            return
        choice, ok = QInputDialog.getItem(
            self, "Load playlist", "Pick:", names, 0, False
        )
        if not ok:
            return
        name, tracks = playlists.load(choice)
        self.transport.queue.clear()
        self.transport.queue.add_many(tracks)
        self._refresh_queue()
        self.statusBar().showMessage(f"Loaded '{name}' ({len(tracks)} tracks)", 4000)

    def _clear_queue(self) -> None:
        self.transport.stop()
        self.transport.queue.clear()
        self._refresh_queue()

    def _remove_track(self, idx: int) -> None:
        self.transport.queue.remove(idx)
        self._refresh_queue()

    # --- ticks -----------------------------------------------------------
    def _refresh_queue(self) -> None:
        self.queue_view.set_tracks(
            self.transport.queue.tracks, self.transport.queue.index
        )
        if self.transport.mixer.has_current and not self.transport.mixer.paused:
            self.btn_play.setText("⏸")
        else:
            self.btn_play.setText("▶")

    def _refresh_status(self) -> None:
        cur = self.transport.queue.current
        if cur is None:
            self.setWindowTitle("CS2 Mic Music")
            return
        state = "▶" if not self.transport.mixer.paused else "⏸"
        self.setWindowTitle(f"{state} {cur.display()} - CS2 Mic Music")
