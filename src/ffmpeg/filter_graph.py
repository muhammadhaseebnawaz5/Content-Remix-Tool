"""
FilterGraph - Builds FFmpeg filter strings.
Uses simple -vf / -af approach for reliability.
"""

import random
from typing import List, Dict, Any, Optional


class FilterGraph:
    """Constructs FFmpeg video/audio filter strings."""

    def __init__(self):
        self._video_filters: List[str] = []
        self._audio_filters: List[str] = []

    def reset(self) -> None:
        self._video_filters.clear()
        self._audio_filters.clear()

    def configure(self, effects: Dict[str, Any], media_info: Optional[Any] = None) -> "FilterGraph":
        self.reset()

        # Transform effects (order matters)
        if effects.get("mirror", {}).get("enabled", False):
            self.add_mirror(effects["mirror"])

        if effects.get("flip", {}).get("enabled", False):
            self.add_flip(effects["flip"])

        if effects.get("rotation", {}).get("enabled", False):
            self.add_rotation(effects["rotation"])

        if effects.get("crop", {}).get("enabled", False):
            self.add_crop(effects["crop"], media_info)

        if effects.get("zoom", {}).get("enabled", False):
            self.add_zoom(effects["zoom"], media_info)

        # Color effects
        if effects.get("preset_filter", {}).get("enabled", False):
            self.add_preset_filter(effects["preset_filter"])

        if effects.get("brightness", {}).get("enabled", False):
            self.add_brightness(effects["brightness"])

        if effects.get("contrast", {}).get("enabled", False):
            self.add_contrast(effects["contrast"])

        if effects.get("saturation", {}).get("enabled", False):
            self.add_saturation(effects["saturation"])

        if effects.get("hue", {}).get("enabled", False):
            self.add_hue(effects["hue"])

        if effects.get("sharpness", {}).get("enabled", False):
            self.add_sharpness(effects["sharpness"])

        if effects.get("noise", {}).get("enabled", False):
            self.add_noise(effects["noise"])

        if effects.get("motion_blur", {}).get("enabled", False):
            self.add_motion_blur(effects["motion_blur"])

        if effects.get("camera_shake", {}).get("enabled", False):
            self.add_camera_shake(effects["camera_shake"])

        if effects.get("stabilization", {}).get("enabled", False):
            self._video_filters.append("deshake")

        if effects.get("border", {}).get("enabled", False):
            self.add_border(effects["border"])

        if effects.get("background", {}).get("enabled", False):
            self.add_background(effects["background"], media_info)

        # Speed is handled separately (setpts for video, atempo for audio)
        if effects.get("speed", {}).get("enabled", False):
            self.add_speed(effects["speed"])

        # Text overlay
        if effects.get("text_overlay", {}).get("enabled", False):
            self.add_text_overlay(effects["text_overlay"], media_info)

        # Watermark
        if effects.get("watermark", {}).get("enabled", False):
            self.add_watermark(effects["watermark"])

        return self

    def add_mirror(self, config: Dict[str, Any]) -> None:
        mode = config.get("mode", "horizontal")
        if config.get("randomize", False):
            mode = random.choice(["horizontal", "vertical", "both", "alternate"])
        if mode == "horizontal":
            self._video_filters.append("hflip")
        elif mode == "vertical":
            self._video_filters.append("vflip")
        elif mode == "both":
            self._video_filters.append("hflip,vflip")
        elif mode == "alternate":
            self._video_filters.append(random.choice(["hflip", "vflip"]))

    def add_flip(self, config: Dict[str, Any]) -> None:
        mode = config.get("mode", "horizontal")
        if mode == "horizontal":
            self._video_filters.append("hflip")
        elif mode == "vertical":
            self._video_filters.append("vflip")

    def add_rotation(self, config: Dict[str, Any]) -> None:
        import math
        mode = config.get("mode", "small")
        angle = config.get("angle", 0)
        if config.get("randomize", False):
            if mode == "small":
                angle = random.uniform(-5, 5)
            elif mode == "large":
                angle = random.uniform(-30, 30)
            elif mode == "clockwise":
                angle = random.uniform(0, 90)
            elif mode == "anticlockwise":
                angle = random.uniform(-90, 0)
            elif mode == "random":
                angle = random.uniform(-180, 180)
        rad = angle * math.pi / 180
        self._video_filters.append(f"rotate=angle={rad:.4f}:fillcolor=black")

    def add_crop(self, config: Dict[str, Any], media_info: Optional[Any] = None) -> None:
        mode = config.get("mode", "center")
        aspect = config.get("aspect_ratio", "16:9")
        if not media_info or not media_info.video_streams:
            return
        w = media_info.video_streams[0].width
        h = media_info.video_streams[0].height
        if w == 0 or h == 0:
            return

        ar_map = {"16:9": 16/9, "4:3": 4/3, "1:1": 1, "9:16": 9/16, "3:2": 3/2}
        target_ar = ar_map.get(aspect, 16/9)
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

        self._video_filters.append(f"crop={new_w}:{new_h}:{x}:{y}")

    def add_zoom(self, config: Dict[str, Any], media_info: Optional[Any] = None) -> None:
        mode = config.get("mode", "dynamic")
        min_z = config.get("min_zoom", 1.0)
        max_z = config.get("max_zoom", 1.5)

        if not media_info or not media_info.video_streams:
            return
        w = media_info.video_streams[0].width
        h = media_info.video_streams[0].height
        if w == 0 or h == 0:
            return

        if mode == "ken_burns":
            start_zoom = random.uniform(min_z, max_z) if config.get("randomize", False) else min_z
            end_zoom = random.uniform(min_z, max_z) if config.get("randomize", False) else max_z
            fps = media_info.video_streams[0].fps or 30
            dur_frames = int(media_info.video_streams[0].duration * fps)
            if dur_frames <= 0:
                dur_frames = 300
            self._video_filters.append(
                f"zoompan=z='if(lte(on,1),{start_zoom},{start_zoom}+({end_zoom}-{start_zoom})*on/{dur_frames})':"
                f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={w}x{h}:fps={fps}"
            )
            return

        if mode == "zoom_in":
            zoom = max_z
        elif mode == "zoom_out":
            zoom = min_z
        elif mode == "dynamic":
            zoom = random.uniform(min_z, max_z) if config.get("randomize", False) else (min_z + max_z) / 2
        else:
            zoom = 1.0

        new_w = int(w / zoom)
        new_h = int(h / zoom)
        x = (w - new_w) // 2
        y = (h - new_h) // 2
        self._video_filters.append(f"crop={new_w}:{new_h}:{x}:{y},scale={w}:{h}")

    def add_preset_filter(self, config: Dict[str, Any]) -> None:
        category = config.get("category", "Vintage")
        style = config.get("style", "Vintage Classic (01)")
        
        import os
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        style_clean = style.lower().replace(" ", "_").replace("(", "").replace(")", "")
        lut_filename = f"{style_clean}.cube"
        lut_path = os.path.join(base_dir, "luts", lut_filename)

        if os.path.exists(lut_path):
            p = lut_path.replace("\\", "/").replace(":", "\\:")
            self._video_filters.append(f"lut3d=file='{p}'")
        else:
            from ..effects.preset_filter import PRESET_FILTERS
            preset = PRESET_FILTERS.get(category, {}).get(style, {})
            vf = preset.get("video_filter", "")
            if vf:
                self._video_filters.append(vf)

    def add_brightness(self, config: Dict[str, Any]) -> None:
        val = self._get_random_or_fixed(config, "value", 0.0, [-0.2, 0.2])
        self._video_filters.append(f"eq=brightness={val:.3f}")

    def add_contrast(self, config: Dict[str, Any]) -> None:
        val = self._get_random_or_fixed(config, "value", 1.0, [0.8, 1.5])
        self._video_filters.append(f"eq=contrast={val:.3f}")

    def add_saturation(self, config: Dict[str, Any]) -> None:
        val = self._get_random_or_fixed(config, "value", 1.0, [0.5, 1.8])
        self._video_filters.append(f"eq=saturation={val:.3f}")

    def add_hue(self, config: Dict[str, Any]) -> None:
        val = self._get_random_or_fixed(config, "value", 0, [-30, 30])
        self._video_filters.append(f"hue=h={val:.1f}")

    def add_sharpness(self, config: Dict[str, Any]) -> None:
        val = self._get_random_or_fixed(config, "value", 1.0, [0.5, 2.0])
        amount = (val - 1.0) * 5.0
        self._video_filters.append(f"unsharp=3:3:{amount:.2f}")

    def add_noise(self, config: Dict[str, Any]) -> None:
        intensity = self._get_random_or_fixed(config, "intensity", 0.05, [0.02, 0.12])
        seed = random.randint(1, 10000)
        self._video_filters.append(f"noise=alls={intensity:.3f}:all_seed={seed}")

    def add_motion_blur(self, config: Dict[str, Any]) -> None:
        frames = config.get("frames", 2)
        if config.get("randomize", False):
            frames = random.randint(2, 5)
        self._video_filters.append(f"tmix=frames={frames}")

    def add_camera_shake(self, config: Dict[str, Any]) -> None:
        intensity = config.get("intensity", "small")
        if config.get("randomize", False):
            intensity = random.choice(["small", "medium", "large"])
        shake_map = {"small": 10, "medium": 25, "large": 50}
        px = shake_map.get(intensity, 10)
        self._video_filters.append(f"crop=iw-{px}:ih-{px}:random(0)*{px}:random(0)*{px},scale=iw:ih")

    def add_border(self, config: Dict[str, Any]) -> None:
        color = config.get("color", "#000000").lstrip("#")
        if len(color) == 6:
            r = int(color[0:2], 16)
            g = int(color[2:4], 16)
            b = int(color[4:6], 16)
            color = f"{r:02X}{g:02X}{b:02X}"
        width = config.get("width", 10)
        self._video_filters.append(f"drawbox=x={width}:y={width}:w=iw-{width*2}:h=ih-{width*2}:color=#{color}:t=fill")

    def add_background(self, config: Dict[str, Any], media_info: Optional[Any] = None) -> None:
        mode = config.get("mode", "blur")
        if mode == "blur":
            self._video_filters.append("split[s0][s1];[s0]boxblur=20:20[bg];[bg][s1]overlay=(W-w)/2:(H-h)/2")
        elif mode == "solid":
            color = config.get("color", "#000000")
            self._video_filters.append(f"pad=iw*1.5:ih*1.5:(ow-iw)/2:(oh-ih)/2:color={color}")

    def add_speed(self, config: Dict[str, Any]) -> None:
        speed = config.get("speed", 1.0)
        if config.get("randomize", False):
            speed = random.choice([0.8, 0.9, 1.1, 1.2])
        # setpts goes to video filters
        self._video_filters.append(f"setpts={1/speed:.4f}*PTS")
        # atempo goes to audio filters
        self._audio_filters.append(self._build_atempo(speed))

    def _build_atempo(self, speed: float) -> str:
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

    def _get_fontfile(self) -> str:
        """Find a suitable system font file for drawtext."""
        import sys
        import os
        if sys.platform == "win32":
            font_paths = [
                "C:/Windows/Fonts/arial.ttf",
                "C:/Windows/Fonts/calibri.ttf",
                "C:/Windows/Fonts/segoeui.ttf",
            ]
        else:
            font_paths = [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
                "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
            ]
        for path in font_paths:
            if os.path.exists(path):
                return path.replace(":", "\\:")
        return ""

    def add_text_overlay(self, config: Dict[str, Any], media_info: Optional[Any] = None) -> None:
        text = config.get("text", "").replace(":", "\\:").replace("'", "\\'")
        position = config.get("position", "center")
        font_size = config.get("font_size", 24)
        color = config.get("color", "#FFFFFF")

        pos_map = {
            "top_left": "x=10:y=10",
            "top_center": "x=(w-text_w)/2:y=10",
            "top_right": "x=w-text_w-10:y=10",
            "center": "x=(w-text_w)/2:y=(h-text_h)/2",
            "bottom_left": "x=10:y=h-text_h-10",
            "bottom_center": "x=(w-text_w)/2:y=h-text_h-10",
            "bottom_right": "x=w-text_w-10:y=h-text_h-10"
        }
        pos = pos_map.get(position, pos_map["center"])
        fontfile = self._get_fontfile()
        font_arg = f":fontfile='{fontfile}'" if fontfile else ""
        self._video_filters.append(f"drawtext=text='{text}'{font_arg}:fontcolor={color}:fontsize={font_size}:{pos}")

    def add_watermark(self, config: Dict[str, Any]) -> None:
        mode = config.get("mode", config.get("type", "replace_text"))
        if mode == "text":
            mode = "replace_text"
        elif mode == "logo":
            mode = "replace_logo"
            
        box = config.get("box", [0, 0, 0, 0])
        position = config.get("position", "bottom_right")
        opacity = config.get("opacity", 0.8)

        has_box = isinstance(box, list) and len(box) == 4 and box[2] > 0 and box[3] > 0
        if has_box:
            x, y, w, h = box
        else:
            x, y, w, h = 0, 0, 0, 0

        if mode == "remove":
            if has_box:
                self._video_filters.append(f"delogo=x={x}:y={y}:w={w}:h={h}")

        elif mode == "replace_text":
            text = config.get("text", "AI Bulk Remix").replace(":", "\\:").replace("'", "\\'")
            font_size = config.get("font_size", 24)
            color = config.get("color", "#FFFFFF")
            
            if has_box:
                self._video_filters.append(f"delogo=x={x}:y={y}:w={w}:h={h}")
                pos = f"x='{x}+({w}-text_w)/2':y='{y}+({h}-text_h)/2'"
            else:
                pos_map = {
                    "top_left": "x=10:y=10",
                    "top_right": "x=w-text_w-10:y=10",
                    "bottom_left": "x=10:y=h-text_h-10",
                    "bottom_right": "x=w-text_w-10:y=h-text_h-10",
                    "center": "x=(w-text_w)/2:y=(h-text_h)/2"
                }
                pos = pos_map.get(position, pos_map["bottom_right"])
                
            fontfile = self._get_fontfile()
            font_arg = f":fontfile='{fontfile}'" if fontfile else ""
            self._video_filters.append(f"drawtext=text='{text}'{font_arg}:fontcolor={color}@{opacity:.2f}:fontsize={font_size}:{pos}")

        elif mode == "replace_logo":
            logo_path = config.get("logo_path", "")
            import os
            if logo_path and os.path.exists(logo_path):
                p = logo_path.replace("\\", "/").replace(":", "\\:")
                if has_box:
                    self._video_filters.append(f"delogo=x={x}:y={y}:w={w}:h={h}")
                    self._video_filters.append(
                        f"movie='{p}',format=rgba,colorchannelmixer=aa={opacity:.2f},scale={w}:{h}[logo_scaled];[in][logo_scaled]overlay=x={x}:y={y}"
                    )
                else:
                    logo_pos_map = {
                        "top_left": "x=10:y=10",
                        "top_right": "x=W-w-10:y=10",
                        "bottom_left": "x=10:y=H-h-10",
                        "bottom_right": "x=W-w-10:y=H-h-10",
                        "center": "x=(W-w)/2:y=(H-h)/2"
                    }
                    pos = logo_pos_map.get(position, logo_pos_map["bottom_right"])
                    self._video_filters.append(
                        f"movie='{p}',format=rgba,colorchannelmixer=aa={opacity:.2f},scale=iw*0.15:-1[logo_scaled];[in][logo_scaled]overlay={pos}"
                    )

    def build_video_filter(self) -> str:
        if not self._video_filters:
            return ""
            
        zoompan_filters = [f for f in self._video_filters if "zoompan" in f]
        other_filters = [f for f in self._video_filters if "zoompan" not in f]
        ordered = other_filters + zoompan_filters

        linear_filters = []
        complex_filters = []
        for f in ordered:
            if ";" in f or "movie=" in f or "[logo_scaled]" in f:
                complex_filters.append(f)
            else:
                linear_filters.append(f)

        if not complex_filters:
            chain = ["format=yuv420p"] + linear_filters
            return ",".join(chain)

        linear_chain = ",".join(["format=yuv420p"] + linear_filters) if linear_filters else "format=yuv420p"
        parts = []
        for cf in complex_filters:
            parts.append(cf)

        full_graph = ";".join(parts)
        if "[in]" in full_graph:
            full_graph = full_graph.replace("[in]", f"[in]{linear_chain}[main];[main]")
        else:
            full_graph = f"[in]{linear_chain}[main];" + full_graph
            
        return full_graph

    def build_audio_filter(self) -> str:
        return ",".join(self._audio_filters)

    def _get_random_or_fixed(self, config: Dict[str, Any], key: str, default: float, range_vals: List[float]) -> float:
        if config.get("randomize", False):
            return round(random.uniform(range_vals[0], range_vals[1]), 3)
        return config.get(key, default)
