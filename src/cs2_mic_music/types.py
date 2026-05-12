from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

TrackKind = Literal["local", "youtube"]


@dataclass(frozen=True)
class Track:
    kind: TrackKind
    title: str
    duration_s: float | None
    location: str
    artist: str | None = None
    extra: dict = field(default_factory=dict)

    def display(self) -> str:
        if self.artist:
            return f"{self.artist} — {self.title}"
        return self.title


SAMPLE_RATE = 48_000
CHANNELS = 2
DTYPE = "float32"
BLOCK_SIZE = 1024


@dataclass
class AudioFormat:
    sample_rate: int = SAMPLE_RATE
    channels: int = CHANNELS
    dtype: str = DTYPE
    block_size: int = BLOCK_SIZE


@dataclass
class DeviceChoice:
    index: int
    name: str
    host_api: str


def app_data_dir() -> Path:
    import os

    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(base) / "cs2-mic-music"


def cache_dir() -> Path:
    p = app_data_dir() / "cache"
    p.mkdir(parents=True, exist_ok=True)
    return p


def playlists_dir() -> Path:
    p = app_data_dir() / "playlists"
    p.mkdir(parents=True, exist_ok=True)
    return p


def config_path() -> Path:
    p = app_data_dir() / "config.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p
