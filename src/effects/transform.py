"""
Transform effects - Mirror, Flip, Rotate, Zoom, Crop, Speed, CameraShake.
"""

import random
import math
from typing import Optional, Any
from .base import BaseEffect, EffectResult


class MirrorEffect(BaseEffect):
    """Mirror effect: horizontal, vertical, both, or alternate."""

    def apply(self, media_info: Optional[Any] = None) -> EffectResult:
        if not self.enabled:
            return EffectResult()
        vf = self.get_ffmpeg_filter(media_info)
        return EffectResult(video_filter=vf, metadata={"mode": self.config.get("mode", "horizontal")})

    def get_ffmpeg_filter(self, media_info: Optional[Any] = None) -> str:
        mode = self.config.get("mode", "horizontal")
        if self.randomize:
            mode = random.choice(["horizontal", "vertical", "both", "alternate"])
        if mode == "horizontal":
            return "hflip"
        elif mode == "vertical":
            return "vflip"
        elif mode == "both":
            return "hflip,vflip"
        elif mode == "alternate":
            return random.choice(["hflip", "vflip"])
        return "hflip"


class FlipEffect(BaseEffect):
    """Flip effect: horizontal or vertical."""

    def apply(self, media_info: Optional[Any] = None) -> EffectResult:
        if not self.enabled:
            return EffectResult()
        return EffectResult(video_filter=self.get_ffmpeg_filter(media_info))

    def get_ffmpeg_filter(self, media_info: Optional[Any] = None) -> str:
        mode = self.config.get("mode", "horizontal")
        if self.randomize:
            mode = random.choice(["horizontal", "vertical"])
        return "hflip" if mode == "horizontal" else "vflip"


class RotateEffect(BaseEffect):
    """Rotation effect with various modes."""

    def apply(self, media_info: Optional[Any] = None) -> EffectResult:
        if not self.enabled:
            return EffectResult()
        angle = self._get_angle()
        rad = angle * math.pi / 180
        vf = f"rotate=angle={rad:.4f}:fillcolor=black"
        return EffectResult(video_filter=vf, metadata={"angle": angle})

    def get_ffmpeg_filter(self, media_info: Optional[Any] = None) -> str:
        angle = self._get_angle()
        rad = angle * math.pi / 180
        return f"rotate=angle={rad:.4f}:fillcolor=black"

    def _get_angle(self) -> float:
        mode = self.config.get("mode", "small")
        if self.randomize:
            mode = random.choice(["small", "large", "clockwise", "anticlockwise", "random"])
        if mode == "small":
            return random.uniform(-5, 5) if self.randomize else self.config.get("angle", 0)
        elif mode == "large":
            return random.uniform(-30, 30)
        elif mode == "clockwise":
            return random.uniform(0, 90)
        elif mode == "anticlockwise":
            return random.uniform(-90, 0)
        elif mode == "random":
            return random.uniform(-180, 180)
        return self.config.get("angle", 0)


class ZoomEffect(BaseEffect):
    """Zoom effect: zoom_in, zoom_out, dynamic, ken_burns."""

    def apply(self, media_info: Optional[Any] = None) -> EffectResult:
        if not self.enabled or not media_info or not media_info.video_streams:
            return EffectResult()
        vf = self.get_ffmpeg_filter(media_info)
        return EffectResult(video_filter=vf, metadata={"mode": self.config.get("mode", "dynamic")})

    def get_ffmpeg_filter(self, media_info: Optional[Any] = None) -> str:
        if not media_info or not media_info.video_streams:
            return ""
        w = media_info.video_streams[0].width
        h = media_info.video_streams[0].height
        if w == 0 or h == 0:
            return ""

        mode = self.config.get("mode", "dynamic")
        min_z = self.config.get("min_zoom", 1.0)
        max_z = self.config.get("max_zoom", 1.5)

        if self.randomize:
            mode = random.choice(["zoom_in", "zoom_out", "dynamic", "ken_burns"])

        if mode == "ken_burns":
            start_zoom = random.uniform(min_z, max_z) if self.randomize else min_z
            end_zoom = random.uniform(min_z, max_z) if self.randomize else max_z
            fps = media_info.video_streams[0].fps or 30
            dur_frames = int(media_info.video_streams[0].duration * fps)
            if dur_frames <= 0:
                dur_frames = 300
            return (
                f"zoompan=z='{start_zoom}+({end_zoom}-{start_zoom})*on/{dur_frames}':"
                f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={dur_frames}:s={w}x{h}:fps={fps}"
            )

        if mode == "zoom_in":
            zoom = max_z
        elif mode == "zoom_out":
            zoom = min_z
        elif mode == "dynamic":
            zoom = random.uniform(min_z, max_z) if self.randomize else (min_z + max_z) / 2
        else:
            zoom = 1.0

        new_w = int(w / zoom)
        new_h = int(h / zoom)
        x = (w - new_w) // 2
        y = (h - new_h) // 2
        return f"crop={new_w}:{new_h}:{x}:{y},scale={w}:{h}"


class CropEffect(BaseEffect):
    """Crop effect with aspect ratio support."""

    ASPECT_RATIOS = {"16:9": 16/9, "4:3": 4/3, "1:1": 1.0, "9:16": 9/16, "3:2": 3/2}

    def apply(self, media_info: Optional[Any] = None) -> EffectResult:
        if not self.enabled or not media_info or not media_info.video_streams:
            return EffectResult()
        vf = self.get_ffmpeg_filter(media_info)
        return EffectResult(video_filter=vf)

    def get_ffmpeg_filter(self, media_info: Optional[Any] = None) -> str:
        if not media_info or not media_info.video_streams:
            return ""
        w = media_info.video_streams[0].width
        h = media_info.video_streams[0].height
        if w == 0 or h == 0:
            return ""

        mode = self.config.get("mode", "center")
        aspect = self.config.get("aspect_ratio", "16:9")
        if self.randomize:
            mode = random.choice(["center", "random"])
            aspect = random.choice(list(self.ASPECT_RATIOS.keys()))

        target_ar = self.ASPECT_RATIOS.get(aspect, 16/9)
        current_ar = w / h

        if current_ar > target_ar:
            new_w = int(h * target_ar)
            new_h = h
            x = (w - new_w) // 2
            y = 0
        else:
            new_w = w
            new_h = int(w / target_ar)
            x = 0
            y = (h - new_h) // 2

        if mode == "random":
            max_x = max(0, w - new_w)
            max_y = max(0, h - new_h)
            x = random.randint(0, max_x)
            y = random.randint(0, max_y)

        return f"crop={new_w}:{new_h}:{x}:{y}"


class SpeedEffect(BaseEffect):
    """Speed change effect for video and audio."""

    def apply(self, media_info: Optional[Any] = None) -> EffectResult:
        if not self.enabled:
            return EffectResult()
        speed = self._get_speed()
        v_filter = f"setpts={1/speed:.4f}*PTS"
        a_filter = self._build_audio_speed_filter(speed)
        return EffectResult(
            video_filter=v_filter,
            audio_filter=a_filter,
            metadata={"speed": speed}
        )

    def get_ffmpeg_filter(self, media_info: Optional[Any] = None) -> str:
        speed = self._get_speed()
        return f"setpts={1/speed:.4f}*PTS"

    def _get_speed(self) -> float:
        if self.randomize:
            return random.choice([0.8, 0.9, 1.1, 1.2])
        return self.config.get("speed", 1.0)

    def _build_audio_speed_filter(self, speed: float) -> str:
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


class CameraShakeEffect(BaseEffect):
    """Camera shake effect with varying intensity."""

    def apply(self, media_info: Optional[Any] = None) -> EffectResult:
        if not self.enabled:
            return EffectResult()
        return EffectResult(video_filter=self.get_ffmpeg_filter(media_info))

    def get_ffmpeg_filter(self, media_info: Optional[Any] = None) -> str:
        intensity = self.config.get("intensity", "small")
        if self.randomize:
            intensity = random.choice(["small", "medium", "large"])
        shake_map = {"small": 10, "medium": 25, "large": 50}
        px = shake_map.get(intensity, 10)
        return f"crop=iw-{px}:ih-{px}:random(0)*{px}:random(0)*{px},scale=iw:ih"
