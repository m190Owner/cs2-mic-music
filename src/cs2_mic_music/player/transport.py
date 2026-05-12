"""High-level playback controller.

The only thing the UI and hotkeys talk to. Owns:
  * the play queue
  * a single ``Mixer``
  * the rules that turn ``play``/``pause``/``next``/``prev`` commands into
    decoder lifecycle events.

Decoder creation from a ``Track`` lives here so that ``sources/`` modules
stay focused on metadata + URI resolution and don't need to know about the
mixer.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from ..audio.decoder import Decoder
from ..audio.mixer import Mixer
from ..types import Track
from .queue import PlayQueue

log = logging.getLogger(__name__)

Listener = Callable[[], None]


class Transport:
    def __init__(
        self,
        queue: PlayQueue,
        mixer: Mixer,
        *,
        crossfade_seconds: float = 4.0,
        loudnorm: bool = True,
    ) -> None:
        self.queue = queue
        self.mixer = mixer
        self.crossfade_seconds = crossfade_seconds
        self.loudnorm = loudnorm
        self._listeners: list[Listener] = []
        self._lock = threading.Lock()
        self._auto_advance_pending = False
        self.mixer.set_on_track_end(self._on_track_ended)

    # --- listeners --------------------------------------------------------
    def add_listener(self, fn: Listener) -> None:
        self._listeners.append(fn)

    def _notify(self) -> None:
        for fn in self._listeners:
            try:
                fn()
            except Exception:
                log.exception("listener raised")

    # --- transport commands ----------------------------------------------
    def play_current(self) -> None:
        with self._lock:
            track = self.queue.current
            if track is None:
                track = self.queue.advance()
            if track is None:
                return
            self._start_track(track, crossfade=False)
        self._notify()

    def play_track_at(self, idx: int) -> None:
        with self._lock:
            track = self.queue.set_index(idx)
            if track is None:
                return
            self._start_track(track, crossfade=False)
        self._notify()

    def pause_toggle(self) -> None:
        self.mixer.set_paused(not self.mixer.paused)
        self._notify()

    def stop(self) -> None:
        self.mixer.stop()
        self._notify()

    def next(self) -> None:
        with self._lock:
            track = self.queue.advance()
            if track is None:
                self.mixer.stop()
            else:
                self._start_track(
                    track, crossfade=self.crossfade_seconds > 0 and self.mixer.has_current
                )
        self._notify()

    def prev(self) -> None:
        with self._lock:
            track = self.queue.back()
            if track is None:
                return
            self._start_track(track, crossfade=False)
        self._notify()

    def set_volume(self, v: float) -> None:
        self.mixer.set_volume(v)
        self._notify()

    def adjust_volume(self, delta: float) -> None:
        self.set_volume(self.mixer.volume + delta)

    # --- internals -------------------------------------------------------
    def _start_track(self, track: Track, *, crossfade: bool) -> None:
        if track.kind == "youtube" and track.extra.get("needs_resolve"):
            # Imported here to keep the audio path independent of yt-dlp at
            # module import time.
            from ..sources import youtube as yt_source

            try:
                track = yt_source.resolve_for_playback(track)
            except Exception as e:
                log.warning("could not resolve '%s' (%s); skipping", track.title, e)
                nxt = self.queue.advance()
                if nxt is None:
                    self.mixer.stop()
                else:
                    self._start_track(nxt, crossfade=False)
                return
        decoder = Decoder(track.location, loudnorm=self.loudnorm)
        xfade = self.crossfade_seconds if crossfade else 0.0
        self.mixer.play(decoder, crossfade_seconds=xfade)
        self.mixer.set_paused(False)

    def _on_track_ended(self) -> None:
        # Called from the audio producer thread. Avoid blocking; mark
        # pending and advance on the next tick from the main thread.
        # Simple approach: just advance directly — the producer can spawn
        # a new decoder; it's bounded work.
        self._auto_advance_pending = True
        threading.Thread(target=self._do_auto_advance, daemon=True).start()

    def _do_auto_advance(self) -> None:
        if not self._auto_advance_pending:
            return
        self._auto_advance_pending = False
        with self._lock:
            track = self.queue.advance()
            if track is None:
                self.mixer.stop()
            else:
                # Natural end: cross-fade for the *next* track only matters at
                # the start of the next gap, not now. Start without xfade.
                self._start_track(track, crossfade=False)
        self._notify()
