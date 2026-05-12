"""User-config persistence.

Stored at ``%APPDATA%/cs2-mic-music/config.json``. Missing fields fall back to
defaults; unknown fields are preserved so future schema changes don't lose
user data.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field, fields

from .types import config_path

log = logging.getLogger(__name__)


@dataclass
class Hotkeys:
    play_pause: str = "<ctrl>+<shift>+p"
    next_track: str = "<ctrl>+<shift>+."
    prev_track: str = "<ctrl>+<shift>+,"
    volume_up: str = "<ctrl>+<shift>+="
    volume_down: str = "<ctrl>+<shift>+-"


@dataclass
class Config:
    primary_device_index: int | None = None
    monitor_device_index: int | None = None
    monitor_enabled: bool = True
    master_volume: float = 0.8
    crossfade_seconds: float = 4.0
    loudnorm_enabled: bool = True
    last_library_folder: str | None = None
    hotkeys: Hotkeys = field(default_factory=Hotkeys)

    @classmethod
    def load(cls) -> "Config":
        p = config_path()
        if not p.exists():
            return cls()
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning("config parse failed (%s); using defaults", e)
            return cls()
        known = {f.name for f in fields(cls)}
        clean = {k: v for k, v in raw.items() if k in known}
        if "hotkeys" in clean and isinstance(clean["hotkeys"], dict):
            clean["hotkeys"] = Hotkeys(
                **{k: v for k, v in clean["hotkeys"].items() if k in {f.name for f in fields(Hotkeys)}}
            )
        return cls(**clean)

    def save(self) -> None:
        p = config_path()
        p.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
