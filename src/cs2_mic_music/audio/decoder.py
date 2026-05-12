"""ffmpeg-backed PCM decoder.

Spawns one ffmpeg subprocess per decoded source. Reads raw float32 stereo PCM
from its stdout in a worker thread, exposing a blocking ``read(n)`` for the
mixer.

Why a thread + queue rather than reading on demand from ffmpeg's stdout?
The audio path needs frames at a steady cadence; pulling synchronously from
the subprocess's pipe risks underrun jitter when ffmpeg pauses on network
I/O (especially for streamed YouTube). The thread keeps a small bounded
buffer pre-filled.
"""

from __future__ import annotations

import logging
import queue
import shutil
import subprocess
import threading
from pathlib import Path

import numpy as np

from ..types import CHANNELS, SAMPLE_RATE

log = logging.getLogger(__name__)

# 2 channels * 4 bytes (float32) = 8 bytes per stereo frame.
BYTES_PER_FRAME = CHANNELS * 4

# Read in ~50ms chunks from ffmpeg.
_CHUNK_FRAMES = SAMPLE_RATE // 20
_CHUNK_BYTES = _CHUNK_FRAMES * BYTES_PER_FRAME

# Bounded buffer: ~2 seconds of audio.
_QUEUE_MAX_CHUNKS = 40


class DecoderError(RuntimeError):
    pass


def _ffmpeg_path() -> str:
    p = shutil.which("ffmpeg")
    if not p:
        raise DecoderError("ffmpeg not found on PATH")
    return p


def _build_command(
    input_uri: str,
    *,
    start_seconds: float = 0.0,
    loudnorm: bool = True,
) -> list[str]:
    cmd: list[str] = [
        _ffmpeg_path(),
        "-hide_banner",
        "-loglevel", "error",
        "-nostdin",
    ]
    if start_seconds > 0:
        cmd += ["-ss", f"{start_seconds:.3f}"]
    cmd += [
        "-i", input_uri,
        "-vn",
        "-ac", str(CHANNELS),
        "-ar", str(SAMPLE_RATE),
        "-f", "f32le",
    ]
    if loudnorm:
        # Single-pass dynamic loudnorm — good enough for live playback.
        cmd += ["-af", "loudnorm=I=-16:TP=-1.5:LRA=11"]
    cmd += ["pipe:1"]
    return cmd


class Decoder:
    """Reads PCM from an ffmpeg subprocess on a background thread.

    Frame layout: float32 stereo, interleaved, ``SAMPLE_RATE`` Hz.
    """

    def __init__(
        self,
        input_uri: str,
        *,
        start_seconds: float = 0.0,
        loudnorm: bool = True,
    ) -> None:
        self._cmd = _build_command(
            input_uri, start_seconds=start_seconds, loudnorm=loudnorm
        )
        self._proc: subprocess.Popen | None = None
        self._q: queue.Queue[np.ndarray | None] = queue.Queue(maxsize=_QUEUE_MAX_CHUNKS)
        self._thread: threading.Thread | None = None
        self._stopped = threading.Event()
        self._leftover: np.ndarray = np.empty((0, CHANNELS), dtype=np.float32)
        self._eof = False

    @classmethod
    def from_file(cls, path: Path, **kwargs) -> "Decoder":
        return cls(str(path), **kwargs)

    @classmethod
    def from_url(cls, url: str, **kwargs) -> "Decoder":
        return cls(url, **kwargs)

    def start(self) -> None:
        if self._proc is not None:
            return
        log.debug("starting ffmpeg: %s", " ".join(self._cmd))
        try:
            self._proc = subprocess.Popen(
                self._cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
        except FileNotFoundError as e:
            raise DecoderError(f"failed to start ffmpeg: {e}") from e
        self._thread = threading.Thread(
            target=self._reader, name="decoder", daemon=True
        )
        self._thread.start()

    def _reader(self) -> None:
        assert self._proc is not None
        assert self._proc.stdout is not None
        try:
            while not self._stopped.is_set():
                buf = self._proc.stdout.read(_CHUNK_BYTES)
                if not buf:
                    break
                arr = np.frombuffer(buf, dtype=np.float32)
                if arr.size % CHANNELS != 0:
                    # Trim partial frame; should be exceedingly rare.
                    arr = arr[: (arr.size // CHANNELS) * CHANNELS]
                arr = arr.reshape(-1, CHANNELS)
                try:
                    self._q.put(arr, timeout=1.0)
                except queue.Full:
                    if self._stopped.is_set():
                        return
        except Exception as e:
            log.warning("decoder reader thread error: %s", e)
        finally:
            try:
                self._q.put_nowait(None)  # sentinel EOF
            except queue.Full:
                pass

    def read(self, n_frames: int) -> tuple[np.ndarray, bool]:
        """Return ``(frames, eof)``. ``frames`` may be shorter than ``n_frames``
        only on EOF. Missing samples on underrun are zero-padded so the audio
        callback always gets exactly ``n_frames``.
        """
        out = np.zeros((n_frames, CHANNELS), dtype=np.float32)
        offset = 0
        # Drain leftover first.
        if self._leftover.shape[0]:
            take = min(self._leftover.shape[0], n_frames)
            out[:take] = self._leftover[:take]
            self._leftover = self._leftover[take:]
            offset += take

        while offset < n_frames and not self._eof:
            try:
                chunk = self._q.get(timeout=0.05)
            except queue.Empty:
                # Underrun — return zeros for what we couldn't fill.
                return out, False
            if chunk is None:
                self._eof = True
                break
            need = n_frames - offset
            if chunk.shape[0] <= need:
                out[offset : offset + chunk.shape[0]] = chunk
                offset += chunk.shape[0]
            else:
                out[offset:] = chunk[:need]
                self._leftover = chunk[need:]
                offset = n_frames
                break
        return out[:offset] if self._eof and offset < n_frames else out, self._eof

    def stop(self) -> None:
        self._stopped.set()
        if self._proc is not None:
            try:
                self._proc.terminate()
            except Exception:
                pass
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
