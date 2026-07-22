"""
ConfigManager - Loads and provides app-wide configuration from defaults.json.
"""

import json
import os
from copy import deepcopy
from typing import Any, Dict, Optional


class ConfigManager:
    """Manages application configuration."""

    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            config_path = os.path.join(base_dir, "config", "defaults.json")
        self._config_path = config_path
        self._config: Dict[str, Any] = {}
        self.load()

    def load(self) -> bool:
        """Load configuration from defaults.json."""
        try:
            with open(self._config_path, "r", encoding="utf-8") as f:
                self._config = json.load(f)
            return True
        except Exception as e:
            print(f"Failed to load config: {e}")
            self._config = self._default_config()
            return False

    def get(self, key: str, default: Any = None) -> Any:
        """Get config value by dot-notation key (e.g., 'app.theme')."""
        keys = key.split(".")
        value = self._config
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return deepcopy(value)

    def set(self, key: str, value: Any) -> None:
        """Set config value by dot-notation key."""
        keys = key.split(".")
        target = self._config
        for k in keys[:-1]:
            if k not in target:
                target[k] = {}
            target = target[k]
        target[keys[-1]] = value

    def get_all(self) -> Dict[str, Any]:
        """Return full configuration copy."""
        return deepcopy(self._config)

    def _default_config(self) -> Dict[str, Any]:
        """Fallback default configuration."""
        return {
            "app": {"max_parallel_workers": 4, "theme": "dark", "version": "1.0.0"},
            "processing": {"max_workers": 4, "max_retries": 3, "timeout_per_video": 600},
            "video": {"default_fps": 30, "default_bitrate": "5M", "crf": 23},
            "export": {
                "gpu_encoders": ["h264_nvenc", "hevc_nvenc", "h264_qsv", "hevc_qsv", "h264_amf", "av1_nvenc"],
                "cpu_encoders": ["libx264", "libx265", "libsvtav1"],
                "resolutions": ["original", "Original (Min 720p)", "720p", "1080p", "2K", "4K"]
            },
            "ai": {"whisper_model": "base", "rembg_model": "u2net"},
            "audio": {"sample_rate": 44100, "fade_duration": 2.0},
            "logging": {"level": "INFO", "max_log_size_mb": 50}
        }
