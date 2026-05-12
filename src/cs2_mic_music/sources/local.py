"""Local file source: build ``Track`` records from on-disk audio."""

from __future__ import annotations

import logging
from pathlib import Path

from ..types import Track

log = logging.getLogger(__name__)

AUDIO_EXTS = {".mp3", ".flac", ".wav", ".m4a", ".aac", ".ogg", ".opus", ".wma"}


def track_from_file(path: Path) -> Track:
    title = path.stem
    artist: str | None = None
    duration: float | None = None
    try:
        from mutagen import File as MutagenFile  # type: ignore

        mf = MutagenFile(str(path), easy=True)
        if mf is not None:
            if mf.info and hasattr(mf.info, "length"):
                duration = float(mf.info.length)
            tags = mf.tags or {}
            t = tags.get("title")
            a = tags.get("artist")
            if t:
                title = t[0] if isinstance(t, list) else str(t)
            if a:
                artist = a[0] if isinstance(a, list) else str(a)
    except Exception as e:
        log.debug("mutagen read failed for %s: %s", path, e)

    return Track(
        kind="local",
        title=title,
        artist=artist,
        duration_s=duration,
        location=str(path),
    )


def scan_folder(folder: Path, *, recursive: bool = True) -> list[Track]:
    if not folder.exists():
        return []
    pattern = "**/*" if recursive else "*"
    tracks: list[Track] = []
    for p in sorted(folder.glob(pattern)):
        if p.is_file() and p.suffix.lower() in AUDIO_EXTS:
            tracks.append(track_from_file(p))
    return tracks
