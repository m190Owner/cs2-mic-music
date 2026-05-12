"""Dual-device audio sink.

A producer thread pulls mixed blocks from the mixer at a steady rate and
writes the same buffer to one or two ``sounddevice.OutputStream``s
(primary → e.g. VB-CABLE Input, monitor → e.g. headphones).

``OutputStream`` is opened in blocking mode (no callback). Each ``write()``
blocks until that stream has room for the block, so the producer's pace is
bounded by the slower of the two devices - keeping them within ~one block
of each other. That's well under perceivable drift for monitoring.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Callable

import numpy as np
import sounddevice as sd

from ..types import CHANNELS, DTYPE, SAMPLE_RATE

log = logging.getLogger(__name__)


@dataclass
class StreamRef:
    device_index: int
    name: str
    stream: sd.OutputStream


class Sink:
    def __init__(self, block_size: int = 1024) -> None:
        self._block_size = block_size
        self._streams: list[StreamRef] = []
        self._producer: threading.Thread | None = None
        self._stopped = threading.Event()
        self._render: Callable[[int], np.ndarray] | None = None
        self._lock = threading.Lock()

    @staticmethod
    def list_output_devices() -> list[tuple[int, str, str]]:
        devs = sd.query_devices()
        host_apis = sd.query_hostapis()
        out: list[tuple[int, str, str]] = []
        for i, d in enumerate(devs):
            if d["max_output_channels"] >= CHANNELS:
                api_name = host_apis[d["hostapi"]]["name"]
                out.append((i, d["name"], api_name))
        return out

    def set_render(self, render: Callable[[int], np.ndarray]) -> None:
        self._render = render

    def open(self, device_indices: list[int]) -> None:
        """Open output streams for the given devices. Closes any existing ones
        first. Pass an empty list to silence output.
        """
        self.close()
        for idx in device_indices:
            try:
                s = sd.OutputStream(
                    device=idx,
                    samplerate=SAMPLE_RATE,
                    channels=CHANNELS,
                    dtype=DTYPE,
                    blocksize=self._block_size,
                )
                s.start()
                name = sd.query_devices(idx)["name"]
                self._streams.append(StreamRef(device_index=idx, name=name, stream=s))
                log.info("opened output stream on device %d (%s)", idx, name)
            except Exception as e:
                log.error("failed to open device %d: %s", idx, e)

    def close(self) -> None:
        for ref in self._streams:
            try:
                ref.stream.stop()
                ref.stream.close()
            except Exception:
                pass
        self._streams = []

    def start(self) -> None:
        if self._producer is not None:
            return
        if self._render is None:
            raise RuntimeError("Sink.render callback not set")
        self._stopped.clear()
        self._producer = threading.Thread(
            target=self._produce, name="sink-producer", daemon=True
        )
        self._producer.start()

    def shutdown(self) -> None:
        self._stopped.set()
        if self._producer is not None:
            self._producer.join(timeout=2)
            self._producer = None
        self.close()

    def _produce(self) -> None:
        assert self._render is not None
        while not self._stopped.is_set():
            block = self._render(self._block_size)
            # Snapshot streams list once per block - open() rebuilds it
            # holding _lock, which we read here.
            with self._lock:
                streams = list(self._streams)
            if not streams:
                # No outputs configured: just throttle so we don't spin.
                self._stopped.wait(self._block_size / SAMPLE_RATE)
                continue
            for ref in streams:
                try:
                    ref.stream.write(block)
                except sd.PortAudioError as e:
                    log.warning("stream %s write error: %s", ref.name, e)
