"""
Effects module - Professional video effect implementations.
Provides transform, color, filter, overlay, and audio effects.
"""

from .base import BaseEffect, EffectResult
from .transform import (
    MirrorEffect, FlipEffect, RotateEffect, ZoomEffect,
    CropEffect, SpeedEffect, CameraShakeEffect
)
from .color import (
    BrightnessEffect, ContrastEffect, SaturationEffect,
    HueEffect, SharpnessEffect, NoiseEffect, MotionBlurEffect
)
from .preset_filter import PresetFilterEffect, PRESET_FILTERS
from .overlay import (
    TextOverlayEffect, WatermarkEffect, BorderEffect,
    BackgroundEffect, LogoEffect
)
from .audio import AudioSpeedEffect, VolumeEffect, FadeEffect
from .factory import EffectFactory

__all__ = [
    "BaseEffect", "EffectResult", "EffectFactory",
    "MirrorEffect", "FlipEffect", "RotateEffect", "ZoomEffect",
    "CropEffect", "SpeedEffect", "CameraShakeEffect",
    "BrightnessEffect", "ContrastEffect", "SaturationEffect",
    "HueEffect", "SharpnessEffect", "NoiseEffect", "MotionBlurEffect",
    "PresetFilterEffect", "PRESET_FILTERS",
    "TextOverlayEffect", "WatermarkEffect", "BorderEffect",
    "BackgroundEffect", "LogoEffect",
    "AudioSpeedEffect", "VolumeEffect", "FadeEffect",
]
