"""
Scanner - Scans directories for supported video files.
"""

import os
from typing import List, Dict, Any
from ..ffmpeg.probe import Probe


class Scanner:
    """Scans directories for video files."""

    SUPPORTED_FORMATS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".ts", ".flv", ".wmv"}

    def __init__(self):
        self._probe = Probe()
        self._cache: Dict[str, Any] = {}

    def scan(self, directory: str, recursive: bool = False) -> List[str]:
        """Scan directory for supported video files."""
        files = []
        if not os.path.isdir(directory):
            return files

        if recursive:
            for root, _, filenames in os.walk(directory):
                for name in filenames:
                    ext = os.path.splitext(name)[1].lower()
                    if ext in self.SUPPORTED_FORMATS:
                        files.append(os.path.join(root, name))
        else:
            for name in os.listdir(directory):
                path = os.path.join(directory, name)
                if os.path.isfile(path):
                    ext = os.path.splitext(name)[1].lower()
                    if ext in self.SUPPORTED_FORMATS:
                        files.append(path)

        return sorted(files)

    def get_info(self, file_path: str) -> Dict[str, Any]:
        """Get cached or fresh info for a file."""
        if file_path not in self._cache:
            self._cache[file_path] = self._probe.get_simple_info(file_path)
        return self._cache[file_path]

    def clear_cache(self) -> None:
        """Clear info cache."""
        self._cache.clear()
