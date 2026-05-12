"""Convenience wrapper that runs YouTube URL resolution off the GUI thread.

Kept in ``player/`` so the UI can fire-and-forget without depending on
``sources/`` internals.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from ..sources import youtube
from ..types import Track

log = logging.getLogger(__name__)


def resolve_async(
    query: str,
    on_ok: Callable[[list[Track]], None],
    on_err: Callable[[str], None],
) -> None:
    def _run():
        try:
            if youtube.is_playlist_url(query):
                tracks = youtube.resolve_playlist(query)
                if not tracks:
                    on_err("playlist returned no tracks")
                    return
            else:
                tracks = [youtube.resolve(query)]
            on_ok(tracks)
        except Exception as e:
            log.exception("youtube resolve failed")
            on_err(str(e))

    threading.Thread(target=_run, name="yt-resolve", daemon=True).start()
