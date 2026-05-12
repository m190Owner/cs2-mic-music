"""Crossfade-aware mixer.

Maintains the currently-playing decoder and (optionally) an outgoing one
during a crossfade. The transport layer is responsible for deciding *when*
to start a crossfade; the mixer just blends amplitudes once told.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

import numpy as np

from ..types import CHANNELS, SAMPLE_RATE
from .decoder import Decoder


@dataclass
class _ActiveTrack:
    decoder: Decoder
    frames_played: int = 0
    fading_out: bool = False
    fade_total_frames: int = 0
    fade_remaining_frames: int = 0


class Mixer:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._current: _ActiveTrack | None = None
        self._fading_out: _ActiveTrack | None = None
        self._master_volume = 1.0
        self._paused = False
        # Set by transport when a track finishes naturally.
        self._on_track_end: callable | None = None

    def set_on_track_end(self, cb) -> None:
        self._on_track_end = cb

    def set_volume(self, v: float) -> None:
        self._master_volume = max(0.0, min(1.5, float(v)))

    @property
    def volume(self) -> float:
        return self._master_volume

    def set_paused(self, paused: bool) -> None:
        self._paused = paused

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def has_current(self) -> bool:
        with self._lock:
            return self._current is not None

    @property
    def current_position_frames(self) -> int:
        with self._lock:
            return self._current.frames_played if self._current else 0

    def play(self, decoder: Decoder, *, crossfade_seconds: float = 0.0) -> None:
        decoder.start()
        with self._lock:
            if self._current is not None and crossfade_seconds > 0:
                # Start a crossfade: existing track fades out, new track fades in.
                fade_frames = int(crossfade_seconds * SAMPLE_RATE)
                # If there was already an outgoing track, drop it abruptly.
                if self._fading_out is not None:
                    self._fading_out.decoder.stop()
                self._fading_out = self._current
                self._fading_out.fading_out = True
                self._fading_out.fade_total_frames = fade_frames
                self._fading_out.fade_remaining_frames = fade_frames
                self._current = _ActiveTrack(
                    decoder=decoder,
                    fade_total_frames=fade_frames,
                    fade_remaining_frames=fade_frames,
                )
            else:
                if self._current is not None:
                    self._current.decoder.stop()
                if self._fading_out is not None:
                    self._fading_out.decoder.stop()
                    self._fading_out = None
                self._current = _ActiveTrack(decoder=decoder)

    def stop(self) -> None:
        with self._lock:
            if self._current is not None:
                self._current.decoder.stop()
                self._current = None
            if self._fading_out is not None:
                self._fading_out.decoder.stop()
                self._fading_out = None

    def render(self, n_frames: int) -> np.ndarray:
        """Pull ``n_frames`` of stereo float32 PCM. Always returns a full block;
        silence on underrun or when paused.
        """
        out = np.zeros((n_frames, CHANNELS), dtype=np.float32)
        if self._paused:
            return out
        with self._lock:
            current = self._current
            outgoing = self._fading_out

        if current is None and outgoing is None:
            return out

        if current is not None:
            block, eof = current.decoder.read(n_frames)
            if block.shape[0] < n_frames:
                # Decoder hit EOF; pad and fire end callback after we mix.
                padded = np.zeros((n_frames, CHANNELS), dtype=np.float32)
                padded[: block.shape[0]] = block
                block = padded
            # Apply fade-in if this track is mid-crossfade.
            if current.fade_remaining_frames > 0:
                block = self._apply_fade(
                    block,
                    current.fade_remaining_frames,
                    current.fade_total_frames,
                    fade_in=True,
                )
                current.fade_remaining_frames = max(
                    0, current.fade_remaining_frames - n_frames
                )
            out += block
            current.frames_played += n_frames
            if eof:
                with self._lock:
                    if self._current is current:
                        self._current = None
                current.decoder.stop()
                if self._on_track_end:
                    try:
                        self._on_track_end()
                    except Exception:
                        pass

        if outgoing is not None:
            block, eof = outgoing.decoder.read(n_frames)
            if block.shape[0] < n_frames:
                padded = np.zeros((n_frames, CHANNELS), dtype=np.float32)
                padded[: block.shape[0]] = block
                block = padded
            block = self._apply_fade(
                block,
                outgoing.fade_remaining_frames,
                outgoing.fade_total_frames,
                fade_in=False,
            )
            outgoing.fade_remaining_frames = max(
                0, outgoing.fade_remaining_frames - n_frames
            )
            out += block
            if eof or outgoing.fade_remaining_frames == 0:
                outgoing.decoder.stop()
                with self._lock:
                    if self._fading_out is outgoing:
                        self._fading_out = None

        out *= self._master_volume
        np.clip(out, -1.0, 1.0, out=out)
        return out

    @staticmethod
    def _apply_fade(
        block: np.ndarray,
        remaining: int,
        total: int,
        *,
        fade_in: bool,
    ) -> np.ndarray:
        n = block.shape[0]
        # Position within fade at the *start* of this block.
        start_done = total - remaining
        idx = np.arange(start_done, start_done + n, dtype=np.float32)
        # Clamp to [0, total]; equal-power (sin/cos) curve.
        t = np.clip(idx / max(total, 1), 0.0, 1.0)
        if fade_in:
            gain = np.sin(t * (np.pi / 2)).astype(np.float32)
        else:
            gain = np.cos(t * (np.pi / 2)).astype(np.float32)
        return block * gain[:, np.newaxis]
