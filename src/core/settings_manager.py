"""
SettingsManager - Persists user preferences (theme, window size, last paths, etc.).
"""

import json
import os
from typing import Any, Dict, Optional


class SettingsManager:
    """Manages user preferences persisted to a JSON file."""

    def __init__(self, settings_dir: Optional[str] = None):
        if settings_dir is None:
            home = os.path.expanduser("~")
            settings_dir = os.path.join(home, ".ai_bulk_remix_studio")
        self._settings_dir = settings_dir
        os.makedirs(self._settings_dir, exist_ok=True)
        self._settings_path = os.path.join(settings_dir, "settings.json")
        self._settings: Dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        """Load settings from disk."""
        if os.path.exists(self._settings_path):
            try:
                with open(self._settings_path, "r", encoding="utf-8") as f:
                    self._settings = json.load(f)
            except Exception:
                self._settings = {}
        else:
            self._settings = self._default_settings()
            self.save()

    def save(self) -> bool:
        """Save settings to disk."""
        try:
            with open(self._settings_path, "w", encoding="utf-8") as f:
                json.dump(self._settings, f, indent=2)
            return True
        except Exception as e:
            print(f"Failed to save settings: {e}")
            return False

    def get(self, key: str, default: Any = None) -> Any:
        """Get a setting value."""
        return self._settings.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set a setting value."""
        self._settings[key] = value
        self.save()

    def _default_settings(self) -> Dict[str, Any]:
        """Default user settings."""
        return {
            "theme": "dark",
            "window_width": 1600,
            "window_height": 1000,
            "last_input_dir": "",
            "last_output_dir": "",
            "last_project_dir": "",
            "recent_projects": [],
            "show_welcome": True,
            "check_updates": True,
            "language": "en"
        }
