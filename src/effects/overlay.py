"""
Overlay effects - Text, Watermark, Border, Background, Logo.
"""

import random
from typing import Optional, Any
from .base import BaseEffect, EffectResult


class TextOverlayEffect(BaseEffect):
    """Text overlay with position and animation support."""

    POS_MAP = {
        "top_left": "x=10:y=10",
        "top_center": "x=(w-text_w)/2:y=10",
        "top_right": "x=w-text_w-10:y=10",
        "center": "x=(w-text_w)/2:y=(h-text_h)/2",
        "bottom_left": "x=10:y=h-text_h-10",
        "bottom_center": "x=(w-text_w)/2:y=h-text_h-10",
        "bottom_right": "x=w-text_w-10:y=h-text_h-10"
    }

    def apply(self, media_info: Optional[Any] = None) -> EffectResult:
        if not self.enabled:
            return EffectResult()
        vf = self.get_ffmpeg_filter(media_info)
        return EffectResult(video_filter=vf, metadata={"text": self.config.get("text", "")})

    def get_ffmpeg_filter(self, media_info: Optional[Any] = None) -> str:
        text = self.config.get("text", "").replace(":", "\\:").replace("'", "\\'")
        position = self.config.get("position", "center")
        font_size = self.config.get("font_size", 24)
        color = self.config.get("color", "#FFFFFF")
        animation = self.config.get("animation", "none")

        pos = self.POS_MAP.get(position, self.POS_MAP["center"])

        filter_str = f"drawtext=text='{text}':fontcolor={color}:fontsize={font_size}:{pos}"

        if animation == "fade" and media_info and media_info.duration > 0:
            dur = media_info.duration
            fade_d = min(2.0, dur / 4)
            filter_str += f":enable='between(t,{fade_d},{dur-fade_d})'"
        elif animation == "scroll":
            filter_str = f"drawtext=text='{text}':fontcolor={color}:fontsize={font_size}:x='w-mod(t*w/10,w+text_w)':y=(h-text_h)/2"

        return filter_str


class WatermarkEffect(BaseEffect):
    """Text or Logo watermark overlay."""

    POS_MAP = {
        "top_left": "x=10:y=10",
        "top_right": "x=w-text_w-10:y=10",
        "bottom_left": "x=10:y=h-text_h-10",
        "bottom_right": "x=w-text_w-10:y=h-text_h-10",
        "center": "x=(w-text_w)/2:y=(h-text_h)/2"
    }

    def apply(self, media_info: Optional[Any] = None) -> EffectResult:
        if not self.enabled:
            return EffectResult()
        vf = self.get_ffmpeg_filter(media_info)
        return EffectResult(video_filter=vf)

    def get_ffmpeg_filter(self, media_info: Optional[Any] = None) -> str:
        mode = self.config.get("mode", self.config.get("type", "replace_text"))
        if mode == "text":
            mode = "replace_text"
        elif mode == "logo":
            mode = "replace_logo"
            
        box = self.config.get("box", [0, 0, 0, 0])
        position = self.config.get("position", "bottom_right")
        opacity = self.config.get("opacity", 0.5)

        # Check if box is valid
        has_box = isinstance(box, list) and len(box) == 4 and box[2] > 0 and box[3] > 0
        if has_box:
            x, y, w, h = box
        else:
            x, y, w, h = 0, 0, 0, 0

        if mode == "remove":
            if has_box:
                return f"delogo=x={x}:y={y}:w={w}:h={h}"
            return ""

        elif mode == "replace_text":
            text = self.config.get("text", "Watermark").replace(":", "\\:").replace("'", "\\'")
            font_size = self.config.get("font_size", 24)
            color = self.config.get("color", "#FFFFFF")
            
            filters = []
            if has_box:
                filters.append(f"delogo=x={x}:y={y}:w={w}:h={h}")
                pos = f"x='{x}+({w}-text_w)/2':y='{y}+({h}-text_h)/2'"
            else:
                pos = self.POS_MAP.get(position, self.POS_MAP["bottom_right"])
                
            filters.append(f"drawtext=text='{text}':fontcolor={color}@{opacity:.2f}:fontsize={font_size}:{pos}")
            return ",".join(filters)

        elif mode == "replace_logo":
            logo_path = self.config.get("logo_path", "")
            import os
            if logo_path and os.path.exists(logo_path):
                p = logo_path.replace("\\", "/").replace(":", "\\:")
                if has_box:
                    return f"movie='{p}',format=rgba,colorchannelmixer=aa={opacity:.2f},scale={w}:{h}[logo_scaled];[in]delogo=x={x}:y={y}:w={w}:h={h}[main];[main][logo_scaled]overlay=x={x}:y={y}"
                else:
                    logo_pos_map = {
                        "top_left": "x=10:y=10",
                        "top_right": "x=W-w-10:y=10",
                        "bottom_left": "x=10:y=H-h-10",
                        "bottom_right": "x=W-w-10:y=H-h-10",
                        "center": "x=(W-w)/2:y=(H-h)/2"
                    }
                    pos = logo_pos_map.get(position, logo_pos_map["bottom_right"])
                    return f"movie='{p}',format=rgba,colorchannelmixer=aa={opacity:.2f},scale=iw*0.15:-1[logo_scaled];[in][logo_scaled]overlay={pos}"
            return ""
        return ""


class BorderEffect(BaseEffect):
    """Border frame effect."""

    def apply(self, media_info: Optional[Any] = None) -> EffectResult:
        if not self.enabled:
            return EffectResult()
        return EffectResult(video_filter=self.get_ffmpeg_filter(media_info))

    def get_ffmpeg_filter(self, media_info: Optional[Any] = None) -> str:
        color = self.config.get("color", "#000000").lstrip("#")
        if len(color) == 6:
            r = int(color[0:2], 16)
            g = int(color[2:4], 16)
            b = int(color[4:6], 16)
            color = f"{r:02X}{g:02X}{b:02X}"
        width = self.config.get("width", 10)
        return f"drawbox=x={width}:y={width}:w=iw-{width*2}:h=ih-{width*2}:color=#{color}:t=fill"


class BackgroundEffect(BaseEffect):
    """Background fill/blur effect for padded videos."""

    def apply(self, media_info: Optional[Any] = None) -> EffectResult:
        if not self.enabled:
            return EffectResult()
        return EffectResult(video_filter=self.get_ffmpeg_filter(media_info))

    def get_ffmpeg_filter(self, media_info: Optional[Any] = None) -> str:
        mode = self.config.get("mode", "blur")
        if mode == "blur":
            return "split[s0][s1];[s0]boxblur=20:20[bg];[bg][s1]overlay=(W-w)/2:(H-h)/2"
        elif mode == "solid":
            color = self.config.get("color", "#000000")
            return f"pad=iw*1.5:ih*1.5:(ow-iw)/2:(oh-ih)/2:color={color}"
        return ""


class LogoEffect(BaseEffect):
    """Image logo overlay effect."""

    POS_MAP = {
        "top_left": "x=10:y=10",
        "top_right": "x=W-w-10:y=10",
        "bottom_left": "x=10:y=H-h-10",
        "bottom_right": "x=W-w-10:y=H-h-10",
        "center": "x=(W-w)/2:y=(H-h)/2"
    }

    def apply(self, media_info: Optional[Any] = None) -> EffectResult:
        if not self.enabled:
            return EffectResult()
        vf = self.get_ffmpeg_filter(media_info)
        return EffectResult(video_filter=vf)

    def get_ffmpeg_filter(self, media_info: Optional[Any] = None) -> str:
        path = self.config.get("path", "")
        if not path:
            return ""
        position = self.config.get("position", "top_right")
        opacity = self.config.get("opacity", 0.8)
        scale = self.config.get("scale", 0.15)
        pos = self.POS_MAP.get(position, self.POS_MAP["top_right"])
        return f"movie='{path}'[logo];[logo]format=rgba,colorchannelmixer=aa={opacity:.2f},scale=iw*{scale}:-1[logo_scaled];[in][logo_scaled]overlay={pos}[out]"
