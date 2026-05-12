"""YouTube source.

Two-mode playback:

* **Cache hit** — track has been downloaded before; return a ``Track`` whose
  ``location`` is the cached file path. Decoder reads the local file.
* **Cache miss** — resolve the direct streamable audio URL with ``yt-dlp``,
  return a ``Track`` whose ``location`` is that URL (the decoder streams it),
  and in parallel kick off a background download to populate the cache for
  next time.

We use yt-dlp's Python API rather than the CLI to keep things simple and to
avoid passing user input into a shell.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ..types import Track, cache_dir

log = logging.getLogger(__name__)


def is_playlist_url(query: str) -> bool:
    """True if ``query`` is a YouTube or YouTube Music URL carrying a playlist.

    Any URL with a ``list=`` query parameter is treated as a playlist —
    including ``watch?v=X&list=Y`` (the browser-bar shape you get while
    watching a video inside a playlist). Pasting that expands the entire
    playlist into the queue.
    """
    if not (query.startswith("http://") or query.startswith("https://")):
        return False
    p = urlparse(query)
    host = (p.hostname or "").lower()
    if "youtube.com" not in host and "youtu.be" not in host:
        return False
    return "list=" in (p.query or "")


def _ytdl_import():
    try:
        import yt_dlp  # type: ignore
        return yt_dlp
    except Exception as e:
        raise RuntimeError(
            "yt-dlp is required for YouTube playback (pip install yt-dlp)"
        ) from e


def _cache_path_for(video_id: str) -> Path:
    return cache_dir() / f"{video_id}.opus"


def _info_to_track(info: dict[str, Any], location: str) -> Track:
    return Track(
        kind="youtube",
        title=info.get("title") or info.get("id") or "Unknown",
        artist=info.get("uploader") or info.get("channel"),
        duration_s=float(info["duration"]) if info.get("duration") else None,
        location=location,
        extra={"video_id": info.get("id", ""), "webpage_url": info.get("webpage_url", "")},
    )


def resolve(query: str) -> Track:
    """Turn a URL or search query into a playable ``Track``.

    If the resolved video is already in the local cache, returns a ``Track``
    pointing at the cached file (no network needed at playback time).
    Otherwise returns a ``Track`` pointing at a streamable direct URL, and
    launches a background cache-download thread.
    """
    yt = _ytdl_import()

    # Decide URL vs search. yt-dlp accepts "ytsearch1:..." for one search hit.
    if not (query.startswith("http://") or query.startswith("https://")):
        search_target = f"ytsearch1:{query}"
    else:
        search_target = query

    opts: dict[str, Any] = {
        "format": "bestaudio/best",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
    }
    with yt.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(search_target, download=False)
        # If a search was performed, info is a playlist-shaped dict.
        if info.get("_type") == "playlist":
            entries = info.get("entries") or []
            if not entries:
                raise RuntimeError(f"no results for {query!r}")
            info = entries[0]

    video_id = info.get("id") or ""
    cached = _cache_path_for(video_id) if video_id else None
    if cached and cached.exists() and cached.stat().st_size > 0:
        log.info("youtube cache hit: %s (%s)", info.get("title"), video_id)
        return _info_to_track(info, str(cached))

    # Pick a stream URL from the resolved formats. yt-dlp puts a flat 'url'
    # on the format chosen by the format selector.
    stream_url = info.get("url")
    if not stream_url:
        # Sometimes 'url' is inside the chosen format entry.
        fmts = info.get("requested_formats") or []
        if fmts:
            stream_url = fmts[0].get("url")
    if not stream_url:
        raise RuntimeError("yt-dlp could not produce a direct stream URL")

    if video_id:
        threading.Thread(
            target=_background_cache,
            args=(info.get("webpage_url") or search_target, video_id),
            name=f"yt-cache-{video_id}",
            daemon=True,
        ).start()

    return _info_to_track(info, stream_url)


def resolve_playlist(url: str) -> list[Track]:
    """Expand a YouTube / YouTube Music playlist URL into a list of ``Track``s.

    Uses yt-dlp's flat extraction so this is fast even for large playlists:
    only id/title/duration/uploader are fetched per entry, no per-video
    stream resolution. Each track is marked ``needs_resolve`` in ``extra``;
    the transport resolves to a cache hit or fresh stream URL on play.

    A single background thread also caches each entry to disk serially so
    subsequent plays are local.
    """
    yt = _ytdl_import()
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "skip_download": True,
    }
    with yt.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    tracks: list[Track] = []
    for entry in info.get("entries") or []:
        video_id = entry.get("id") or ""
        if not video_id:
            continue
        webpage = entry.get("url") or f"https://www.youtube.com/watch?v={video_id}"
        duration = float(entry["duration"]) if entry.get("duration") else None
        tracks.append(
            Track(
                kind="youtube",
                title=entry.get("title") or video_id,
                artist=entry.get("uploader") or entry.get("channel"),
                duration_s=duration,
                location=webpage,
                extra={
                    "video_id": video_id,
                    "webpage_url": webpage,
                    "needs_resolve": True,
                },
            )
        )

    if tracks:
        threading.Thread(
            target=_serial_cache_playlist,
            args=([(t.extra["webpage_url"], t.extra["video_id"]) for t in tracks],),
            name="yt-playlist-cache",
            daemon=True,
        ).start()

    return tracks


def resolve_for_playback(track: Track) -> Track:
    """Turn a flat-extracted playlist ``Track`` into a playable one.

    Fast path: if the video is already cached, return a fresh Track pointing
    at the cache file with no network hit. Otherwise fall back to ``resolve``
    which fetches a stream URL and kicks off background caching.
    """
    video_id = track.extra.get("video_id") or ""
    if video_id:
        cached = _cache_path_for(video_id)
        if cached.exists() and cached.stat().st_size > 0:
            return Track(
                kind="youtube",
                title=track.title,
                artist=track.artist,
                duration_s=track.duration_s,
                location=str(cached),
                extra={**track.extra, "needs_resolve": False},
            )
    webpage = track.extra.get("webpage_url") or track.location
    return resolve(webpage)


def _serial_cache_playlist(items: list[tuple[str, str]]) -> None:
    """Download each ``(source_url, video_id)`` to the cache in series.

    Skips entries already cached. Sequential rather than parallel to avoid
    saturating the network and to keep yt-dlp's extractor cookies stable.
    """
    for source_url, video_id in items:
        target = _cache_path_for(video_id)
        if target.exists() and target.stat().st_size > 0:
            continue
        try:
            _background_cache(source_url, video_id)
        except Exception:
            log.exception("playlist cache failed for %s", video_id)


def _background_cache(source_url: str, video_id: str) -> None:
    yt = _ytdl_import()
    target = _cache_path_for(video_id)
    tmp = target.with_suffix(target.suffix + ".part")
    opts = {
        "format": "bestaudio/best",
        "outtmpl": str(tmp),
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "overwrites": True,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "opus",
                "preferredquality": "192",
            }
        ],
    }
    try:
        with yt.YoutubeDL(opts) as ydl:
            ydl.download([source_url])
        # The postprocessor renames to .opus; find whatever ended up next to tmp.
        for candidate in tmp.parent.glob(f"{tmp.stem}.*"):
            if candidate.suffix.lower() in (".opus", ".m4a", ".webm", ".mp3"):
                candidate.replace(target)
                log.info("cached youtube track: %s", target.name)
                return
        if tmp.exists():
            tmp.replace(target)
    except Exception as e:
        log.warning("background cache failed for %s: %s", video_id, e)
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass
