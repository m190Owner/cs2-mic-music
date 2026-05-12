"""Entry point — wires config, audio engine, hotkeys, and GUI together."""

from __future__ import annotations

import logging
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from .audio.mixer import Mixer
from .audio.sink import Sink
from .config import Config
from .hotkeys import HotkeyManager
from .player.queue import PlayQueue
from .player.transport import Transport
from .ui.main_window import MainWindow

log = logging.getLogger(__name__)


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def main() -> int:
    _configure_logging()
    config = Config.load()

    app = QApplication(sys.argv)
    app.setApplicationName("CS2 Mic Music")

    queue = PlayQueue()
    mixer = Mixer()
    mixer.set_volume(config.master_volume)
    sink = Sink()
    sink.set_render(mixer.render)
    transport = Transport(
        queue, mixer,
        crossfade_seconds=config.crossfade_seconds,
        loudnorm=config.loudnorm_enabled,
    )
    hotkeys = HotkeyManager()

    def apply_devices(primary: int | None, monitor: int | None) -> None:
        devices: list[int] = []
        if primary is not None:
            devices.append(primary)
        if monitor is not None and monitor != primary:
            devices.append(monitor)
        sink.open(devices)

    win = MainWindow(config, transport, apply_devices)

    # Wire hotkeys via Qt::QueuedConnection (default for cross-thread emits).
    hotkeys.start(
        config.hotkeys,
        on_play_pause=lambda: win.hk_play_pause.emit(),
        on_next=lambda: win.hk_next.emit(),
        on_prev=lambda: win.hk_prev.emit(),
        on_vol_up=lambda: win.hk_vol_up.emit(),
        on_vol_down=lambda: win.hk_vol_down.emit(),
    )

    # Open devices from saved config, then start the producer.
    primary = config.primary_device_index
    monitor = config.monitor_device_index if config.monitor_enabled else None
    apply_devices(primary, monitor)
    sink.start()

    win.show()
    try:
        code = app.exec()
    finally:
        hotkeys.stop()
        sink.shutdown()
        mixer.stop()
    return code


if __name__ == "__main__":
    sys.exit(main())
