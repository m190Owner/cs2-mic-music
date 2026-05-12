from __future__ import annotations

import random
from dataclasses import dataclass, field

from ..types import Track


@dataclass
class PlayQueue:
    tracks: list[Track] = field(default_factory=list)
    index: int = -1
    repeat: bool = False
    shuffle: bool = False

    def add(self, track: Track) -> None:
        self.tracks.append(track)

    def add_many(self, tracks: list[Track]) -> None:
        self.tracks.extend(tracks)

    def insert_next(self, track: Track) -> None:
        if self.index < 0:
            self.tracks.insert(0, track)
        else:
            self.tracks.insert(self.index + 1, track)

    def remove(self, idx: int) -> None:
        if 0 <= idx < len(self.tracks):
            self.tracks.pop(idx)
            if idx < self.index:
                self.index -= 1
            elif idx == self.index:
                # Current track removed; index now points at next or -1.
                self.index = min(self.index, len(self.tracks) - 1)

    def clear(self) -> None:
        self.tracks = []
        self.index = -1

    @property
    def current(self) -> Track | None:
        if 0 <= self.index < len(self.tracks):
            return self.tracks[self.index]
        return None

    def set_index(self, idx: int) -> Track | None:
        if 0 <= idx < len(self.tracks):
            self.index = idx
            return self.tracks[idx]
        return None

    def advance(self) -> Track | None:
        if not self.tracks:
            return None
        if self.shuffle and len(self.tracks) > 1:
            choices = [i for i in range(len(self.tracks)) if i != self.index]
            self.index = random.choice(choices)
            return self.tracks[self.index]
        nxt = self.index + 1
        if nxt >= len(self.tracks):
            if self.repeat:
                self.index = 0
            else:
                self.index = -1
                return None
        else:
            self.index = nxt
        return self.tracks[self.index]

    def back(self) -> Track | None:
        if not self.tracks:
            return None
        prev = self.index - 1
        if prev < 0:
            if self.repeat:
                self.index = len(self.tracks) - 1
            else:
                return self.tracks[self.index] if self.index >= 0 else None
        else:
            self.index = prev
        return self.tracks[self.index]

    def peek_next(self) -> Track | None:
        """Return the track that ``advance()`` would yield, without mutating."""
        if not self.tracks:
            return None
        if self.shuffle and len(self.tracks) > 1:
            # Can't peek a shuffle deterministically; report None so the
            # transport skips pre-decoding the next track in shuffle mode.
            return None
        nxt = self.index + 1
        if nxt >= len(self.tracks):
            return self.tracks[0] if self.repeat else None
        return self.tracks[nxt]
