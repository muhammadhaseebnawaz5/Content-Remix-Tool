"""
Preset filter / LUT effect.
Supports high-quality simulated FFmpeg filters or custom external .cube LUT files.
"""

import os
from typing import Optional, Any, Dict
from .base import BaseEffect, EffectResult

PRESET_FILTERS: Dict[str, Dict[str, Dict[str, str]]] = {
    "Vintage": {
        "Vintage Classic (01)": {
            "description": "Light yellow tint, low contrast (Purani films jaisa)",
            "video_filter": "colorbalance=rm=0.08:gm=0.04:bm=-0.08:rh=0.08:gh=0.04:bh=-0.08,eq=contrast=0.85"
        },
        "Vintage Fade (02)": {
            "description": "Faded blacks, soft look (80s ki tasweer jaisa)",
            "video_filter": "curves=r='0/0.08 1/0.92':g='0/0.08 1/0.92':b='0/0.08 1/0.92',eq=contrast=0.85:saturation=0.9"
        }
    },
    "Film": {
        "Kodak Cinematic (01)": {
            "description": "Rich colors, high contrast, perfect for outdoor",
            "video_filter": "eq=contrast=1.18:saturation=1.25:brightness=-0.02,colorbalance=rm=0.05:bm=-0.05"
        },
        "Fuji Soft (02)": {
            "description": "Greenish-blue tones, soft highlights (Aesthetic look)",
            "video_filter": "colorbalance=rm=-0.05:gm=0.06:bm=0.04,eq=contrast=0.9:saturation=1.05"
        }
    },
    "Moss": {
        "Deep Moss (01)": {
            "description": "Dark green tones, moody, forest vibes ke liye",
            "video_filter": "eq=brightness=-0.04:contrast=1.12:saturation=0.75,colorbalance=rm=-0.05:gm=0.08:bm=-0.05"
        },
        "Pale Moss (02)": {
            "description": "Light desaturated green, clean and cold look",
            "video_filter": "eq=brightness=0.03:contrast=1.05:saturation=0.65,colorbalance=rm=-0.04:gm=0.04:bm=0.06"
        }
    },
    "Barn": {
        "Warm Barn (01)": {
            "description": "Golden hour look, heavy orange and brown tones",
            "video_filter": "colorbalance=rm=0.12:gm=0.04:bm=-0.12:rh=0.08:bh=-0.08,eq=contrast=1.08:saturation=1.15:brightness=0.01"
        },
        "Rustic Barn (02)": {
            "description": "Dark woody look, high contrast, texturized",
            "video_filter": "eq=brightness=-0.02:contrast=1.15:saturation=0.85,colorbalance=rm=0.06:gm=0.02:bm=-0.06,unsharp=3:3:0.8"
        }
    }
}


class PresetFilterEffect(BaseEffect):
    """Applies preset filter looks or uses .cube files in the luts/ directory if present."""

    def apply(self, media_info: Optional[Any] = None) -> EffectResult:
        if not self.enabled:
            return EffectResult()

        category = self.config.get("category", "Vintage")
        style = self.config.get("style", "Vintage Classic (01)")

        # Resolve path to project root
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        
        # Sanitize style name to match safe filename
        # e.g., "Vintage Classic (01)" -> "vintage_classic_01.cube"
        style_clean = style.lower().replace(" ", "_").replace("(", "").replace(")", "")
        lut_filename = f"{style_clean}.cube"
        lut_path = os.path.join(base_dir, "luts", lut_filename)

        if os.path.exists(lut_path):
            # Escape path for FFmpeg filter parsing (Windows path support)
            escaped_path = lut_path.replace("\\", "/").replace(":", "\\:")
            vf = f"lut3d=file='{escaped_path}'"
            method = "lut3d"
        else:
            preset = PRESET_FILTERS.get(category, {}).get(style, {})
            vf = preset.get("video_filter", "")
            method = "simulated"

        return EffectResult(
            video_filter=vf,
            metadata={"category": category, "style": style, "method": method}
        )

    def get_ffmpeg_filter(self, media_info: Optional[Any] = None) -> str:
        res = self.apply(media_info)
        return res.video_filter
