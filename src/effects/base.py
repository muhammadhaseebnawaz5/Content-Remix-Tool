"""
BaseEffect - Abstract base class for all video effects.
Every effect must implement apply() and get_ffmpeg_filter().
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List


@dataclass
class EffectResult:
    """Result of applying an effect."""
    video_filter: str = ""
    audio_filter: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    success: bool = True
    error: str = ""


class BaseEffect(ABC):
    """Abstract base class for all video effects."""

    def __init__(self, name: str, config: Optional[Dict[str, Any]] = None):
        self.name = name
        self.config = config or {}
        self.enabled = self.config.get("enabled", False)
        self.randomize = self.config.get("randomize", False)

    @abstractmethod
    def apply(self, media_info: Optional[Any] = None) -> EffectResult:
        """Apply the effect and return FFmpeg filter string(s)."""
        pass

    @abstractmethod
    def get_ffmpeg_filter(self, media_info: Optional[Any] = None) -> str:
        """Return the raw FFmpeg filter string for this effect."""
        pass

    def is_enabled(self) -> bool:
        return self.enabled

    def update_config(self, config: Dict[str, Any]) -> None:
        """Update effect configuration."""
        self.config.update(config)
        self.enabled = self.config.get("enabled", False)
        self.randomize = self.config.get("randomize", False)

    def get_params(self) -> Dict[str, Any]:
        """Return current parameters for logging/debugging."""
        return {
            "name": self.name,
            "enabled": self.enabled,
            "randomize": self.randomize,
            "config": self.config
        }

    def validate(self) -> bool:
        """Validate effect configuration."""
        return True
