"""
Audio effects - Speed, Volume, Fade.
"""

from typing import Optional, Any
from .base import BaseEffect, EffectResult


class AudioSpeedEffect(BaseEffect):
    """Audio speed change using atempo filter chain."""

    def apply(self, media_info: Optional[Any] = None) -> EffectResult:
        if not self.enabled:
            return EffectResult()
        speed = self.config.get("speed", 1.0)
        af = self._build_atempo_chain(speed)
        return EffectResult(audio_filter=af, metadata={"speed": speed})

    def get_ffmpeg_filter(self, media_info: Optional[Any] = None) -> str:
        speed = self.config.get("speed", 1.0)
        return self._build_atempo_chain(speed)

    def _build_atempo_chain(self, speed: float) -> str:
        if 0.5 <= speed <= 2.0:
            return f"atempo={speed:.4f}"
        chains = []
        remaining = speed
        while remaining > 2.0:
            chains.append("atempo=2.0")
            remaining /= 2.0
        while remaining < 0.5:
            chains.append("atempo=0.5")
            remaining /= 0.5
        chains.append(f"atempo={remaining:.4f}")
        return ",".join(chains)


class VolumeEffect(BaseEffect):
    """Volume adjustment effect."""

    def apply(self, media_info: Optional[Any] = None) -> EffectResult:
        if not self.enabled:
            return EffectResult()
        db = self.config.get("db", 0)
        return EffectResult(audio_filter=f"volume={db}dB", metadata={"db": db})

    def get_ffmpeg_filter(self, media_info: Optional[Any] = None) -> str:
        db = self.config.get("db", 0)
        return f"volume={db}dB"


class FadeEffect(BaseEffect):
    """Audio fade in/out effect."""

    def apply(self, media_info: Optional[Any] = None) -> EffectResult:
        if not self.enabled or not media_info:
            return EffectResult()
        duration = media_info.duration
        fade_d = self.config.get("fade_duration", 2.0)
        af = f"afade=t=in:ss=0:d={fade_d},afade=t=out:st={max(0, duration-fade_d)}:d={fade_d}"
        return EffectResult(audio_filter=af, metadata={"fade_duration": fade_d})

    def get_ffmpeg_filter(self, media_info: Optional[Any] = None) -> str:
        if not media_info:
            return ""
        duration = media_info.duration
        fade_d = self.config.get("fade_duration", 2.0)
        return f"afade=t=in:ss=0:d={fade_d},afade=t=out:st={max(0, duration-fade_d)}:d={fade_d}"
