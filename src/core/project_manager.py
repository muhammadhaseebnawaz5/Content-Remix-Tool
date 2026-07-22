"""
ProjectManager - Handles .aibrs project files (save/load).
Stores complete pipeline configuration in JSON.
"""

import json
import os
import time
from copy import deepcopy
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional


@dataclass
class ProjectMeta:
    name: str = "Untitled Project"
    version: str = "1.0.0"
    created: str = ""
    modified: str = ""


@dataclass
class SourceConfig:
    input_dir: str = ""
    output_dir: str = ""
    files: List[str] = field(default_factory=list)
    recursive_scan: bool = False


@dataclass
class ExportConfig:
    format: str = "mp4"
    resolution: str = "original"
    bitrate: str = "5M"
    fps: int = 30
    encoder: str = "libx264"


@dataclass
class ProcessingConfig:
    parallel_workers: int = 4
    gpu_acceleration: bool = True


class ProjectManager:
    """Manages project lifecycle and .aibrs files."""

    FILE_EXTENSION = ".aibrs"

    def __init__(self):
        self._project: Dict[str, Any] = {}
        self._file_path: Optional[str] = None
        self._modified = False

    def create_new(self, name: str = "Untitled Project") -> Dict[str, Any]:
        """Create a new empty project."""
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        self._project = {
            "project": {
                "name": name,
                "version": "1.0.0",
                "created": now,
                "modified": now
            },
            "sources": {
                "input_dir": "",
                "output_dir": "",
                "files": [],
                "recursive_scan": False
            },
            "effects": {},
            "watermark": {"enabled": False, "mode": "text", "position": "bottom_right"},
            "text_overlay": {"enabled": False, "text": "", "position": "center", "animation": "fade"},
            "subtitles": {"enabled": False, "source": "whisper"},
            "voice": {"enabled": False, "mode": "tts"},
            "audio": {"background_music": None, "sound_effects": None},
            "intro_outro": {"intro": None, "outro": None},
            "logo": {"enabled": False, "path": "", "opacity": 0.8, "position": "top_right"},
            "transition": {"enabled": False, "mode": "fade", "duration": 1.0},
            "ai_remix": {"enabled": True, "randomize": True, "duplicate_prevention": True},
            "export": {"format": "mp4", "resolution": "original", "bitrate": "5M", "fps": 30, "encoder": "libx264"},
            "processing": {"parallel_workers": 4, "gpu_acceleration": True}
        }
        self._file_path = None
        self._modified = False
        return deepcopy(self._project)

    def save(self, file_path: str) -> bool:
        """Save project to JSON file."""
        try:
            self._project["project"]["modified"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(self._project, f, indent=2, ensure_ascii=False)
            self._file_path = file_path
            self._modified = False
            return True
        except Exception as e:
            print(f"Failed to save project: {e}")
            return False

    def load(self, file_path: str) -> Optional[Dict[str, Any]]:
        """Load project from JSON file."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                self._project = json.load(f)
            self._file_path = file_path
            self._modified = False
            return deepcopy(self._project)
        except Exception as e:
            print(f"Failed to load project: {e}")
            return None

    def add_source_file(self, path: str) -> None:
        """Add a source video file to the project."""
        if path not in self._project["sources"]["files"]:
            self._project["sources"]["files"].append(path)
            self._modified = True

    def remove_source_file(self, path: str) -> None:
        """Remove a source video file."""
        if path in self._project["sources"]["files"]:
            self._project["sources"]["files"].remove(path)
            self._modified = True

    def update_effect_settings(self, name: str, settings: Dict[str, Any]) -> None:
        """Update settings for a specific effect."""
        self._project["effects"][name] = settings
        self._modified = True

    def get_effect_settings(self, name: str) -> Dict[str, Any]:
        """Get settings for a specific effect."""
        return deepcopy(self._project["effects"].get(name, {}))

    def update_export_settings(self, settings: Dict[str, Any]) -> None:
        """Update export settings."""
        self._project["export"].update(settings)
        self._modified = True

    def update_processing_settings(self, settings: Dict[str, Any]) -> None:
        """Update processing settings."""
        self._project["processing"].update(settings)
        self._modified = True

    def get_summary(self) -> str:
        """Return human-readable project summary."""
        p = self._project.get("project", {})
        s = self._project.get("sources", {})
        e = self._project.get("effects", {})
        enabled_effects = [k for k, v in e.items() if isinstance(v, dict) and v.get("enabled", False)]
        lines = [
            f"Project: {p.get('name', 'Untitled')}",
            f"Version: {p.get('version', '1.0.0')}",
            f"Created: {p.get('created', 'N/A')}",
            f"Sources: {len(s.get('files', []))} files",
            f"Output: {s.get('output_dir', 'Not set')}",
            f"Enabled Effects: {', '.join(enabled_effects) if enabled_effects else 'None'}",
        ]
        return "\n".join(lines)

    @property
    def project_data(self) -> Dict[str, Any]:
        return deepcopy(self._project)

    @property
    def file_path(self) -> Optional[str]:
        return self._file_path

    @property
    def is_modified(self) -> bool:
        return self._modified

    def set_modified(self, value: bool = True) -> None:
        self._modified = value
