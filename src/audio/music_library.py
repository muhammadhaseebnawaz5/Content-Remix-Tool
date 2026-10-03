"""Music-track discovery and thread-safe selection for batch processing."""

import os
import random
import threading
from typing import Dict, List, Optional

from ..ffmpeg.probe import Probe

MUSIC_EXTENSIONS = {
    ".mp3",
    ".wav",
    ".m4a",
    ".aac",
    ".ogg",
    ".flac",
    ".opus",
    ".wma",
}


def scan_music_folder(folder: str) -> List[str]:
    """Find supported audio tracks in a folder and its sub-folders."""
    if not folder or not os.path.isdir(folder):
        return []

    tracks = []
    for root, _, filenames in os.walk(folder):
        for filename in filenames:
            if os.path.splitext(filename)[1].lower() in MUSIC_EXTENSIONS:
                tracks.append(os.path.join(root, filename))
    return sorted(tracks)


class MusicLibrary:
    """Thread-safe track picker shared by batch-processing workers."""

    def __init__(self, tracks: List[str], mode: str = "shuffle"):
        self._tracks = [track for track in tracks if os.path.isfile(track)]
        self._mode = mode
        self._lock = threading.Lock()
        self._queue: List[str] = []
        self._sequence_index = 0
        self._durations: Dict[str, float] = {}
        self._probe = Probe()

    def __len__(self) -> int:
        return len(self._tracks)

    def duration_of(self, path: str) -> float:
        with self._lock:
            cached_duration = self._durations.get(path)
        if cached_duration is not None:
            return cached_duration

        duration = float(self._probe.analyze(path).duration or 0.0)
        with self._lock:
            self._durations[path] = duration
        return duration

    def next_track(self) -> Optional[str]:
        with self._lock:
            if not self._tracks:
                return None
            if self._mode == "sequential":
                track = self._tracks[self._sequence_index % len(self._tracks)]
                self._sequence_index += 1
                return track
            if self._mode == "random":
                return random.choice(self._tracks)
            if not self._queue:
                self._queue = self._tracks[:]
                random.shuffle(self._queue)
            return self._queue.pop()
