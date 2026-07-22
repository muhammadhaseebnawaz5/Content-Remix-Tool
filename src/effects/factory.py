"""
EffectFactory - Creates and manages all video/audio effects.
Provides a unified interface to build complete filter chains.
"""

from typing import Dict, Any, List, Optional, Type
from .base import BaseEffect, EffectResult
from .transform import (
    MirrorEffect, FlipEffect, RotateEffect, ZoomEffect,
    CropEffect, SpeedEffect, CameraShakeEffect
)
from .color import (
    BrightnessEffect, ContrastEffect, SaturationEffect,
    HueEffect, SharpnessEffect, NoiseEffect, MotionBlurEffect,
    StabilizationEffect
)
from .preset_filter import PresetFilterEffect
from .overlay import (
    TextOverlayEffect, WatermarkEffect, BorderEffect,
    BackgroundEffect, LogoEffect
)
from .audio import AudioSpeedEffect, VolumeEffect, FadeEffect


class EffectFactory:
    """Factory for creating and chaining effects."""

    EFFECT_REGISTRY: Dict[str, Type[BaseEffect]] = {
        # Transform
        "mirror": MirrorEffect,
        "flip": FlipEffect,
        "rotation": RotateEffect,
        "zoom": ZoomEffect,
        "crop": CropEffect,
        "speed": SpeedEffect,
        "camera_shake": CameraShakeEffect,
        # Color
        "preset_filter": PresetFilterEffect,
        "brightness": BrightnessEffect,
        "contrast": ContrastEffect,
        "saturation": SaturationEffect,
        "hue": HueEffect,
        "sharpness": SharpnessEffect,
        "noise": NoiseEffect,
        "motion_blur": MotionBlurEffect,
        "stabilization": StabilizationEffect,
        # Overlay
        "text_overlay": TextOverlayEffect,
        "watermark": WatermarkEffect,
        "border": BorderEffect,
        "background": BackgroundEffect,
        "logo": LogoEffect,
        # Audio
        "audio_speed": AudioSpeedEffect,
        "volume": VolumeEffect,
        "fade": FadeEffect,
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self._effects: Dict[str, BaseEffect] = {}
        self._build_effects()

    def _build_effects(self) -> None:
        """Instantiate all effects from config."""
        effects_cfg = self.config.get("effects", {})
        for name, effect_class in self.EFFECT_REGISTRY.items():
            cfg = effects_cfg.get(name, {"enabled": False})
            self._effects[name] = effect_class(name, cfg)

    def create_effect(self, name: str, config: Dict[str, Any]) -> Optional[BaseEffect]:
        """Create a single effect by name."""
        effect_class = self.EFFECT_REGISTRY.get(name)
        if effect_class:
            return effect_class(name, config)
        return None

    def get_effect(self, name: str) -> Optional[BaseEffect]:
        """Get an instantiated effect."""
        return self._effects.get(name)

    def get_enabled_effects(self) -> List[BaseEffect]:
        """Get all enabled effects."""
        return [e for e in self._effects.values() if e.is_enabled()]

    def build_video_chain(self, media_info: Optional[Any] = None) -> str:
        """Build complete video filter chain from all enabled effects."""
        filters = []
        for effect in self.get_enabled_effects():
            if effect.name in ("audio_speed", "volume", "fade"):
                continue  # Skip audio-only effects
            vf = effect.get_ffmpeg_filter(media_info)
            if vf:
                filters.append(vf)
        return ",".join(filters)

    def build_audio_chain(self, media_info: Optional[Any] = None) -> str:
        """Build complete audio filter chain from all enabled effects."""
        filters = []
        for effect in self.get_enabled_effects():
            if effect.name in ("audio_speed", "volume", "fade"):
                af = effect.get_ffmpeg_filter(media_info)
                if af:
                    filters.append(af)
        return ",".join(filters)

    def apply_all(self, media_info: Optional[Any] = None) -> Dict[str, Any]:
        """Apply all effects and return complete filter configuration."""
        video_filters = []
        audio_filters = []
        metadata = {}

        for effect in self.get_enabled_effects():
            result = effect.apply(media_info)
            if result.video_filter:
                video_filters.append(result.video_filter)
            if result.audio_filter:
                audio_filters.append(result.audio_filter)
            metadata[effect.name] = result.metadata

        return {
            "video_filter": ",".join(video_filters),
            "audio_filter": ",".join(audio_filters),
            "metadata": metadata
        }

    def get_effect_params(self) -> Dict[str, Dict[str, Any]]:
        """Get parameters of all effects for logging."""
        return {name: effect.get_params() for name, effect in self._effects.items()}

    def update_effect(self, name: str, config: Dict[str, Any]) -> None:
        """Update a specific effect's configuration."""
        if name in self._effects:
            self._effects[name].update_config(config)

    def list_available(self) -> List[str]:
        """List all available effect names."""
        return list(self.EFFECT_REGISTRY.keys())

    def count_enabled(self) -> int:
        """Count enabled effects."""
        return len(self.get_enabled_effects())
