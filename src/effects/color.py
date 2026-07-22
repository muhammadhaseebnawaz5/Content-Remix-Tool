"""
Color effects - Brightness, Contrast, Saturation, Hue, Sharpness, Noise, MotionBlur.
"""

import random
from typing import Optional, Any
from .base import BaseEffect, EffectResult


class BrightnessEffect(BaseEffect):
    """Brightness adjustment effect."""

    def apply(self, media_info: Optional[Any] = None) -> EffectResult:
        if not self.enabled:
            return EffectResult()
        val = self._get_value()
        return EffectResult(video_filter=f"eq=brightness={val:.3f}", metadata={"brightness": val})

    def get_ffmpeg_filter(self, media_info: Optional[Any] = None) -> str:
        val = self._get_value()
        return f"eq=brightness={val:.3f}"

    def _get_value(self) -> float:
        if self.randomize:
            r = self.config.get("range", [-0.2, 0.2])
            return round(random.uniform(r[0], r[1]), 3)
        return self.config.get("value", 0.0)


class ContrastEffect(BaseEffect):
    """Contrast adjustment effect."""

    def apply(self, media_info: Optional[Any] = None) -> EffectResult:
        if not self.enabled:
            return EffectResult()
        val = self._get_value()
        return EffectResult(video_filter=f"eq=contrast={val:.3f}", metadata={"contrast": val})

    def get_ffmpeg_filter(self, media_info: Optional[Any] = None) -> str:
        val = self._get_value()
        return f"eq=contrast={val:.3f}"

    def _get_value(self) -> float:
        if self.randomize:
            r = self.config.get("range", [0.8, 1.5])
            return round(random.uniform(r[0], r[1]), 3)
        return self.config.get("value", 1.0)


class SaturationEffect(BaseEffect):
    """Saturation adjustment effect."""

    def apply(self, media_info: Optional[Any] = None) -> EffectResult:
        if not self.enabled:
            return EffectResult()
        val = self._get_value()
        return EffectResult(video_filter=f"eq=saturation={val:.3f}", metadata={"saturation": val})

    def get_ffmpeg_filter(self, media_info: Optional[Any] = None) -> str:
        val = self._get_value()
        return f"eq=saturation={val:.3f}"

    def _get_value(self) -> float:
        if self.randomize:
            r = self.config.get("range", [0.5, 1.8])
            return round(random.uniform(r[0], r[1]), 3)
        return self.config.get("value", 1.0)


class HueEffect(BaseEffect):
    """Hue shift effect."""

    def apply(self, media_info: Optional[Any] = None) -> EffectResult:
        if not self.enabled:
            return EffectResult()
        val = self._get_value()
        return EffectResult(video_filter=f"hue=h={val:.1f}", metadata={"hue": val})

    def get_ffmpeg_filter(self, media_info: Optional[Any] = None) -> str:
        val = self._get_value()
        return f"hue=h={val:.1f}"

    def _get_value(self) -> float:
        if self.randomize:
            r = self.config.get("range", [-30, 30])
            return round(random.uniform(r[0], r[1]), 1)
        return self.config.get("value", 0)


class SharpnessEffect(BaseEffect):
    """Sharpness/unsharp mask effect."""

    def apply(self, media_info: Optional[Any] = None) -> EffectResult:
        if not self.enabled:
            return EffectResult()
        val = self._get_value()
        amount = (val - 1.0) * 5.0
        return EffectResult(video_filter=f"unsharp=3:3:{amount:.2f}", metadata={"sharpness": val})

    def get_ffmpeg_filter(self, media_info: Optional[Any] = None) -> str:
        val = self._get_value()
        amount = (val - 1.0) * 5.0
        return f"unsharp=3:3:{amount:.2f}"

    def _get_value(self) -> float:
        if self.randomize:
            r = self.config.get("range", [0.5, 2.0])
            return round(random.uniform(r[0], r[1]), 3)
        return self.config.get("value", 1.0)


class NoiseEffect(BaseEffect):
    """Film grain / noise effect."""

    def apply(self, media_info: Optional[Any] = None) -> EffectResult:
        if not self.enabled:
            return EffectResult()
        intensity = self._get_intensity()
        seed = random.randint(1, 10000)
        vf = f"noise=alls={intensity:.3f}:all_seed={seed}"
        return EffectResult(video_filter=vf, metadata={"intensity": intensity, "seed": seed})

    def get_ffmpeg_filter(self, media_info: Optional[Any] = None) -> str:
        intensity = self._get_intensity()
        seed = random.randint(1, 10000)
        return f"noise=alls={intensity:.3f}:all_seed={seed}"

    def _get_intensity(self) -> float:
        if self.randomize:
            return round(random.uniform(0.02, 0.12), 3)
        return self.config.get("intensity", 0.05)


class MotionBlurEffect(BaseEffect):
    """Motion blur via temporal mixing."""

    def apply(self, media_info: Optional[Any] = None) -> EffectResult:
        if not self.enabled:
            return EffectResult()
        frames = self._get_frames()
        return EffectResult(video_filter=f"tmix=frames={frames}", metadata={"frames": frames})

    def get_ffmpeg_filter(self, media_info: Optional[Any] = None) -> str:
        frames = self._get_frames()
        return f"tmix=frames={frames}"

    def _get_frames(self) -> int:
        if self.randomize:
            return random.randint(2, 5)
        return self.config.get("frames", 2)


class StabilizationEffect(BaseEffect):
    """Video stabilization using deshake."""

    def apply(self, media_info: Optional[Any] = None) -> EffectResult:
        if not self.enabled:
            return EffectResult()
        return EffectResult(video_filter="deshake")

    def get_ffmpeg_filter(self, media_info: Optional[Any] = None) -> str:
        return "deshake"
