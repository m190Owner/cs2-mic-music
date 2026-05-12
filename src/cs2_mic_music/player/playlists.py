from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path

from ..types import Track, playlists_dir

log = logging.getLogger(__name__)


def _safe_name(name: str) -> str:
    keep = "-_. "
    return "".join(c for c in name if c.isalnum() or c in keep).strip() or "untitled"


def save(name: str, tracks: list[Track]) -> Path:
    path = playlists_dir() / f"{_safe_name(name)}.json"
    data = {"name": name, "tracks": [asdict(t) for t in tracks]}
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    log.info("saved playlist '%s' (%d tracks)", name, len(tracks))
    return path


def load(name_or_path: str | Path) -> tuple[str, list[Track]]:
    path = Path(name_or_path)
    if not path.exists():
        path = playlists_dir() / f"{_safe_name(str(name_or_path))}.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    tracks = [Track(**t) for t in raw.get("tracks", [])]
    return raw.get("name", path.stem), tracks


def list_all() -> list[str]:
    return sorted(p.stem for p in playlists_dir().glob("*.json"))


def delete(name: str) -> bool:
    path = playlists_dir() / f"{_safe_name(name)}.json"
    if path.exists():
        path.unlink()
        return True
    return False
