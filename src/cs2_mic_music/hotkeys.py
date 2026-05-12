"""Global hotkeys via pynput.

Owns a single ``GlobalHotKeys`` listener thread; rebuilds it when bindings
change. Hotkey callbacks just enqueue a command to a callback you provide
(typically wired to ``Transport`` via a Qt signal so the work runs on the
GUI thread).
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from .config import Hotkeys

log = logging.getLogger(__name__)


def _import_pynput():
    try:
        from pynput import keyboard  # type: ignore
        return keyboard
    except Exception as e:
        log.warning("pynput unavailable: %s — global hotkeys disabled", e)
        return None


class HotkeyManager:
    def __init__(self) -> None:
        self._listener = None
        self._kb = _import_pynput()

    def start(
        self,
        bindings: Hotkeys,
        *,
        on_play_pause: Callable[[], None],
        on_next: Callable[[], None],
        on_prev: Callable[[], None],
        on_vol_up: Callable[[], None],
        on_vol_down: Callable[[], None],
    ) -> None:
        if self._kb is None:
            return
        self.stop()
        try:
            mapping = {
                bindings.play_pause: on_play_pause,
                bindings.next_track: on_next,
                bindings.prev_track: on_prev,
                bindings.volume_up: on_vol_up,
                bindings.volume_down: on_vol_down,
            }
            self._listener = self._kb.GlobalHotKeys(mapping)
            self._listener.start()
            log.info("global hotkeys active")
        except Exception as e:
            log.warning("failed to bind hotkeys: %s", e)
            self._listener = None

    def stop(self) -> None:
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None
