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

    def configure(
        self, effects: Dict[str, Any], media_info: Optional[Any] = None
    ) -> "FilterGraph":
        self.reset()

        # ----------------------------------------------------------------
        # Watermark remove/replace runs FIRST — before any geometry-changing
        # effects (mirror, crop, zoom) so that the box coordinates recorded
        # against the original frame are still valid.
        # ----------------------------------------------------------------
        if effects.get("watermark", {}).get("enabled", False):
            if effects["watermark"].get("mode") == "remove_replace":
                self.add_watermark(effects["watermark"])

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

        # Watermark add_only mode (or if watermark was already handled above, skip)
        if effects.get("watermark", {}).get("enabled", False):
            if effects["watermark"].get("mode") != "remove_replace":
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

    def add_crop(
        self, config: Dict[str, Any], media_info: Optional[Any] = None
    ) -> None:
        mode = config.get("mode", "center")
        aspect = config.get("aspect_ratio", "16:9")
        if not media_info or not media_info.video_streams:
            return
        w = media_info.video_streams[0].width
        h = media_info.video_streams[0].height
        if w == 0 or h == 0:
            return

        ar_map = {"16:9": 16 / 9, "4:3": 4 / 3, "1:1": 1, "9:16": 9 / 16, "3:2": 3 / 2}
        target_ar = ar_map.get(aspect, 16 / 9)
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

    def add_zoom(
        self, config: Dict[str, Any], media_info: Optional[Any] = None
    ) -> None:
        mode = config.get("mode", "dynamic")
        min_z = config.get("min_zoom", 1.0)
        max_z = config.get("max_zoom", config.get("zoom_level", 1.5))

        # Clamp zoom bounds to valid range — a zoom < 1.0 means the cropped
        # region would be LARGER than the source frame, producing black output.
        min_z = max(1.0, min_z)
        max_z = max(1.0, max_z)
        if max_z < min_z:
            max_z = min_z

        if not media_info or not media_info.video_streams:
            return
        w = media_info.video_streams[0].width
        h = media_info.video_streams[0].height
        if w == 0 or h == 0:
            return

        if mode == "ken_burns":
            start_zoom = (
                random.uniform(min_z, max_z)
                if config.get("randomize", False)
                else min_z
            )
            end_zoom = (
                random.uniform(min_z, max_z)
                if config.get("randomize", False)
                else max_z
            )
            # Ensure start != end to avoid a static zoompan (valid but pointless)
            if abs(start_zoom - end_zoom) < 0.01:
                end_zoom = min(start_zoom + 0.1, 2.0)
            fps = media_info.video_streams[0].fps or 30
            dur_frames = int(media_info.video_streams[0].duration * fps)
            if dur_frames <= 0:
                dur_frames = 300
            self._video_filters.append(
                f"zoompan=z='if(lte(on,1),{start_zoom:.4f},{start_zoom:.4f}+({end_zoom:.4f}-{start_zoom:.4f})*on/{dur_frames})':"
                f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={w}x{h}:fps={fps}"
            )
            return

        if mode == "zoom_in":
            zoom = max_z
        elif mode == "zoom_out":
            zoom = min_z
        elif mode == "dynamic":
            zoom = (
                random.uniform(min_z, max_z)
                if config.get("randomize", False)
                else (min_z + max_z) / 2
            )
        else:
            zoom = max(1.0, config.get("zoom_level", max_z))

        # Clamp the final zoom value too (defensive)
        zoom = max(1.0, zoom)
        new_w = int(w / zoom)
        new_h = int(h / zoom)
        # Safety clamp: crop region must fit inside source frame
        new_w = max(2, min(new_w, w))
        new_h = max(2, min(new_h, h))
        x = (w - new_w) // 2
        y = (h - new_h) // 2
        self._video_filters.append(f"crop={new_w}:{new_h}:{x}:{y},scale={w}:{h}")

    def add_preset_filter(self, config: Dict[str, Any]) -> None:
        category = config.get("category", "Vintage")
        style = config.get("style", "Vintage Classic (01)")

        import os

        base_dir = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
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

    def add_camera_shake(
        self, config: Dict[str, Any], media_info: Optional[Any] = None
    ) -> None:
        intensity = config.get("intensity", 0.5)
        if config.get("randomize", False):
            intensity = random.choice([0.25, 0.5, 1.0, 1.5, 2.0])

        if isinstance(intensity, str):
            cleaned = intensity.replace("%", "").strip()
            try:
                intensity = float(cleaned)
            except ValueError:
                intensity = 0.5

        intensity = max(0.0, min(2.0, float(intensity)))
        if not media_info or not media_info.video_streams:
            return

        width = media_info.video_streams[0].width
        height = media_info.video_streams[0].height
        if width <= 0 or height <= 0:
            return

        displacement_x = max(1, int(round(width * (intensity / 100.0))))
        displacement_y = max(1, int(round(height * (intensity / 100.0))))
        self._video_filters.append(
            f"crop=iw-{displacement_x}:ih-{displacement_y}:random(0)*{displacement_x}:random(0)*{displacement_y},scale=iw:ih"
        )

    def add_border(self, config: Dict[str, Any]) -> None:
        color = config.get("color", "#000000").lstrip("#")
        if len(color) == 6:
            r = int(color[0:2], 16)
            g = int(color[2:4], 16)
            b = int(color[4:6], 16)
            color = f"{r:02X}{g:02X}{b:02X}"
        width = config.get("width", 10)
        self._video_filters.append(
            f"drawbox=x={width}:y={width}:w=iw-{width*2}:h=ih-{width*2}:color=#{color}:t=fill"
        )

    def add_background(
        self, config: Dict[str, Any], media_info: Optional[Any] = None
    ) -> None:
        mode = config.get("mode", "blur")
        if mode == "blur":
            self._video_filters.append(
                "split[s0][s1];[s0]boxblur=20:20[bg];[bg][s1]overlay=(W-w)/2:(H-h)/2"
            )
        elif mode == "solid":
            color = config.get("color", "#000000")
            self._video_filters.append(
                f"pad=iw*1.5:ih*1.5:(ow-iw)/2:(oh-ih)/2:color={color}"
            )

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

    def _get_fontfile(self, font_family: str = "Arial", font_style: str = "Normal") -> str:
        """Map a (font_family, font_style) pair to a real .ttf/.otf file path.

        Resolution order:
        1. Windows system fonts  (C:/Windows/Fonts/)
        2. Linux/macOS standard paths
        3. Generic fallback (first existing system font)

        Returns an FFmpeg-safe path with colons escaped, or "" if nothing found.
        """
        import sys
        import os

        # Normalise style
        style = (font_style or "Normal").strip()
        bold = "Bold" in style
        italic = "Italic" in style

        # Windows system font map: (family, bold, italic) -> filename
        WIN_FONT_DIR = "C:/Windows/Fonts"
        WIN_MAP = {
            ("Arial",           False, False): "arial.ttf",
            ("Arial",           True,  False): "arialbd.ttf",
            ("Arial",           False, True):  "ariali.ttf",
            ("Arial",           True,  True):  "arialbi.ttf",
            ("Times New Roman", False, False): "times.ttf",
            ("Times New Roman", True,  False): "timesbd.ttf",
            ("Times New Roman", False, True):  "timesi.ttf",
            ("Times New Roman", True,  True):  "timesbi.ttf",
            ("Impact",          False, False): "impact.ttf",
            ("Impact",          True,  False): "impact.ttf",  # no bold variant
            ("Impact",          False, True):  "impact.ttf",
            ("Impact",          True,  True):  "impact.ttf",
            ("Verdana",         False, False): "verdana.ttf",
            ("Verdana",         True,  False): "verdanab.ttf",
            ("Verdana",         False, True):  "verdanai.ttf",
            ("Verdana",         True,  True):  "verdanaz.ttf",
            ("Georgia",         False, False): "georgia.ttf",
            ("Georgia",         True,  False): "georgiab.ttf",
            ("Georgia",         False, True):  "georgiai.ttf",
            ("Georgia",         True,  True):  "georgiaz.ttf",
            ("Roboto",          False, False): "Roboto-Regular.ttf",
            ("Roboto",          True,  False): "Roboto-Bold.ttf",
            ("Roboto",          False, True):  "Roboto-Italic.ttf",
            ("Roboto",          True,  True):  "Roboto-BoldItalic.ttf",
        }

        # Linux/macOS font map
        LINUX_MAP = {
            ("Arial",           False, False): "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            ("Arial",           True,  False): "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            ("Arial",           False, True):  "/usr/share/fonts/truetype/liberation/LiberationSans-Italic.ttf",
            ("Arial",           True,  True):  "/usr/share/fonts/truetype/liberation/LiberationSans-BoldItalic.ttf",
            ("Times New Roman", False, False): "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
            ("Times New Roman", True,  False): "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
            ("Times New Roman", False, True):  "/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf",
            ("Times New Roman", True,  True):  "/usr/share/fonts/truetype/liberation/LiberationSerif-BoldItalic.ttf",
            ("Roboto",          False, False): "/usr/share/fonts/truetype/roboto/hinted/Roboto-Regular.ttf",
            ("Roboto",          True,  False): "/usr/share/fonts/truetype/roboto/hinted/Roboto-Bold.ttf",
            ("Roboto",          False, True):  "/usr/share/fonts/truetype/roboto/hinted/Roboto-Italic.ttf",
            ("Roboto",          True,  True):  "/usr/share/fonts/truetype/roboto/hinted/Roboto-BoldItalic.ttf",
        }

        # Roboto bundled alongside the app (fallback for any platform)
        _app_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        BUNDLED_ROBOTO = {
            (False, False): os.path.join(_app_root, "fonts", "Roboto-Regular.ttf"),
            (True,  False): os.path.join(_app_root, "fonts", "Roboto-Bold.ttf"),
            (False, True):  os.path.join(_app_root, "fonts", "Roboto-Italic.ttf"),
            (True,  True):  os.path.join(_app_root, "fonts", "Roboto-BoldItalic.ttf"),
        }

        key = (font_family, bold, italic)

        # 1. Try Windows system font
        if sys.platform == "win32":
            filename = WIN_MAP.get(key)
            if filename:
                candidate = os.path.join(WIN_FONT_DIR, filename)
                if os.path.exists(candidate):
                    return candidate.replace("\\", "/").replace(":", "\\:")

        # 2. Try Linux/macOS system font
        linux_path = LINUX_MAP.get(key)
        if linux_path and os.path.exists(linux_path):
            return linux_path.replace(":", "\\:")

        # 3. Try bundled Roboto
        bundled = BUNDLED_ROBOTO.get((bold, italic))
        if bundled and os.path.exists(bundled):
            return bundled.replace("\\", "/").replace(":", "\\:")

        # 4. Last-resort: first existing system font regardless of family
        if sys.platform == "win32":
            fallbacks = [
                os.path.join(WIN_FONT_DIR, "arial.ttf"),
                os.path.join(WIN_FONT_DIR, "calibri.ttf"),
                os.path.join(WIN_FONT_DIR, "segoeui.ttf"),
            ]
        else:
            fallbacks = [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
                "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
            ]
        for path in fallbacks:
            if os.path.exists(path):
                return path.replace("\\", "/").replace(":", "\\:")
        return ""

    def add_text_overlay(
        self, config: Dict[str, Any], media_info: Optional[Any] = None
    ) -> None:
        text = config.get("text", "").replace(":", "\\:").replace("'", "\\'")
        position = config.get("position", "center")
        font_size = config.get("font_size", 24)
        color = config.get("color", "#FFFFFF")
        font_family = config.get("font_family", "Arial")
        font_style = config.get("font_style", "Normal")

        pos_map = {
            "top_left": "x=10:y=10",
            "top_center": "x=(w-text_w)/2:y=10",
            "top_right": "x=w-text_w-10:y=10",
            "center_left": "x=10:y=(h-text_h)/2",
            "center": "x=(w-text_w)/2:y=(h-text_h)/2",
            "center_right": "x=w-text_w-10:y=(h-text_h)/2",
            "bottom_left": "x=10:y=h-text_h-10",
            "bottom_center": "x=(w-text_w)/2:y=h-text_h-10",
            "bottom_right": "x=w-text_w-10:y=h-text_h-10",
        }
        pos = pos_map.get(position, pos_map["center"])
        fontfile = self._get_fontfile(font_family, font_style)
        font_arg = f":fontfile='{fontfile}'" if fontfile else ""
        self._video_filters.append(
            f"drawtext=text='{text}'{font_arg}:fontcolor={color}:fontsize={font_size}:{pos}"
        )

    def add_watermark(self, config: Dict[str, Any]) -> None:
        mode = config.get("mode", "add_only")
        box = config.get("box", [0, 0, 0, 0])
        position = config.get("position", "bottom_right")
        opacity = config.get("opacity", 0.8)

        has_box = isinstance(box, list) and len(box) == 4 and box[2] > 0 and box[3] > 0
        if has_box:
            x, y, w, h = box
        else:
            x, y, w, h = 0, 0, 0, 0

        def _build_drawtext_filter(
            text: str,
            font_size: int,
            color: str,
            text_opacity: float,
            font_style: str,
            font_family: str,
            background_enabled: bool,
            background_color: str,
            background_style: str,
            background_opacity: float,
            pos: str,
            fontfile: str = "",
        ) -> str:
            style_parts = []
            if font_style and font_style != "Normal":
                style_parts.append(font_style)
            font_name = font_family or "Arial"
            if style_parts:
                font_label = f"{font_name} {' '.join(style_parts)}"
            else:
                font_label = font_name
            font_arg = f":fontfile='{fontfile}'" if fontfile else ""
            filter_parts = [
                f"drawtext=text='{text}'{font_arg}:fontcolor={color}@{text_opacity:.2f}:fontsize={font_size}:font='{font_label}'"
            ]
            if background_enabled and background_style != "No Background":
                boxcolor = background_color or "#000000"
                boxopacity = max(0.0, min(1.0, background_opacity))
                if background_style == "Rounded Box":
                    filter_parts[
                        0
                    ] += f":box=1:boxcolor={boxcolor}@{boxopacity:.2f}:boxborderw=6:boxbordercolor={boxcolor}@{boxopacity:.2f}:borderw=3:bordercolor=white@0.0"
                elif background_style == "Semi-transparent Box":
                    filter_parts[
                        0
                    ] += f":box=1:boxcolor={boxcolor}@{boxopacity:.2f}:boxborderw=6"
                else:
                    filter_parts[
                        0
                    ] += f":box=1:boxcolor={boxcolor}@{boxopacity:.2f}:boxborderw=6"
            filter_parts[0] += f":{pos}"
            return "".join(filter_parts)

        if mode == "add_only":
            content_type = config.get("content_type", "text")
            if content_type == "logo":
                logo_path = config.get("logo_path", "")
                import os

                if logo_path and os.path.exists(logo_path):
                    p = logo_path.replace("\\", "/").replace(":", "\\:")
                    pos_map_logo = {
                        "top_left":     "x=10:y=10",
                        "top_center":   "x=(W-w)/2:y=10",
                        "top_right":    "x=W-w-10:y=10",
                        "center_left":  "x=10:y=(H-h)/2",
                        "center":       "x=(W-w)/2:y=(H-h)/2",
                        "center_right": "x=W-w-10:y=(H-h)/2",
                        "bottom_left":  "x=10:y=H-h-10",
                        "bottom_center":"x=(W-w)/2:y=H-h-10",
                        "bottom_right": "x=W-w-10:y=H-h-10",
                    }
                    logo_pos = pos_map_logo.get(position, pos_map_logo["bottom_right"])
                    # scale2ref sizes the logo to 14% of the VIDEO's width,
                    # clamped to [32, 320] px so it's never oversized or tiny.
                    self._video_filters.append(
                        f"movie='{p}',format=rgba,colorchannelmixer=aa={opacity:.2f}[logo_raw];"
                        f"[logo_raw][in]scale2ref=w='min(max(main_w*0.14\\,32)\\,320)':h=-1[logo_scaled][vid];"
                        f"[vid][logo_scaled]overlay={logo_pos}"
                    )
            else:
                text = (
                    config.get("text", "AI Bulk Remix")
                    .replace(":", "\\:")
                    .replace("'", "\\'")
                )
                font_size = config.get("font_size", 24)
                color = config.get("color", "#FFFFFF")
                text_opacity = config.get("text_opacity", 1.0)
                font_style = config.get("font_style", "Normal")
                font_family = config.get("font_family", "Arial")
                background_enabled = config.get("background_enabled", False)
                background_color = config.get("background_color", "#000000")
                background_style = config.get("background_style", "No Background")
                background_opacity = config.get("background_opacity", 0.6)
                pos_map = {
                    "top_left": "x=10:y=10",
                    "top_center": "x=(w-text_w)/2:y=10",
                    "top_right": "x=w-text_w-10:y=10",
                    "center_left": "x=10:y=(h-text_h)/2",
                    "center": "x=(w-text_w)/2:y=(h-text_h)/2",
                    "center_right": "x=w-text_w-10:y=(h-text_h)/2",
                    "bottom_left": "x=10:y=h-text_h-10",
                    "bottom_center": "x=(w-text_w)/2:y=h-text_h-10",
                    "bottom_right": "x=w-text_w-10:y=h-text_h-10",
                }
                pos = pos_map.get(position, pos_map["bottom_right"])
                fontfile = self._get_fontfile(font_family, font_style)
                self._video_filters.append(
                    _build_drawtext_filter(
                        text=text,
                        font_size=font_size,
                        color=color,
                        text_opacity=text_opacity,
                        font_style=font_style,
                        font_family=font_family,
                        background_enabled=background_enabled,
                        background_color=background_color,
                        background_style=background_style,
                        background_opacity=background_opacity,
                        pos=pos,
                        fontfile=fontfile,
                    )
                )
            return

        if mode == "remove_replace":
            remove_only = config.get("removal_method", "replace") == "remove_only"
            removal_quality = config.get("removal_quality", "fast")
            if has_box and removal_quality != "inpaint":
                self._video_filters.append(f"delogo=x={x}:y={y}:w={w}:h={h}")
            if remove_only:
                return

            # Determine where the replacement should be placed.
            # replace_position == "same_as_removed_area" (or empty) keeps the old
            # behaviour of placing the new content at the box coordinates.
            # Any other position name uses the standard screen-position map.
            replace_position = config.get("replace_position", "same_as_removed_area")
            use_box_position = (
                has_box and replace_position in ("same_as_removed_area", "", None)
            )

            content_type = config.get("content_type", "text")
            if content_type == "logo":
                logo_path = config.get("replace_logo_path") or config.get(
                    "logo_path", ""
                )
                import os

                if logo_path and os.path.exists(logo_path):
                    p = logo_path.replace("\\", "/").replace(":", "\\:")
                    if use_box_position:
                        # Place replacement logo at the exact box the user drew
                        self._video_filters.append(
                            f"movie='{p}',format=rgba,colorchannelmixer=aa={opacity:.2f},scale={w}:{h}[logo_scaled];[in][logo_scaled]overlay=x={x}:y={y}"
                        )
                    else:
                        # User picked a different position — use video-relative placement
                        pos_map = {
                            "top_left": "x=10:y=10",
                            "top_center": "x=(W-w)/2:y=10",
                            "top_right": "x=W-w-10:y=10",
                            "center_left": "x=10:y=(H-h)/2",
                            "center": "x=(W-w)/2:y=(H-h)/2",
                            "center_right": "x=W-w-10:y=(H-h)/2",
                            "bottom_left": "x=10:y=H-h-10",
                            "bottom_center": "x=(W-w)/2:y=H-h-10",
                            "bottom_right": "x=W-w-10:y=H-h-10",
                        }
                        pos = pos_map.get(replace_position, pos_map["bottom_right"])
                        self._video_filters.append(
                            f"movie='{p}',format=rgba,colorchannelmixer=aa={opacity:.2f}[logo_raw];"
                            f"[logo_raw][in]scale2ref=w='min(max(main_w*0.14\\,32)\\,320)':h=-1[logo_scaled][vid];"
                            f"[vid][logo_scaled]overlay={pos}"
                        )
            else:
                text = (
                    config.get("replace_text", config.get("text", "AI Bulk Remix"))
                    .replace(":", "\\:")
                    .replace("'", "\\'")
                )
                font_size = config.get("replace_font_size", config.get("font_size", 24))
                color = config.get("replace_color", config.get("color", "#FFFFFF"))
                text_opacity = config.get(
                    "replace_text_opacity", config.get("text_opacity", 1.0)
                )
                font_style = config.get(
                    "replace_font_style", config.get("font_style", "Normal")
                )
                font_family = config.get(
                    "replace_font_family", config.get("font_family", "Arial")
                )
                background_enabled = config.get("replace_background_enabled", False)
                background_color = config.get("replace_background_color", "#000000")
                background_style = config.get(
                    "replace_background_style", "No Background"
                )
                background_opacity = config.get("replace_background_opacity", 0.6)

                if use_box_position:
                    # Place within the cleared box area, honouring inner alignment
                    inner_pos_map = {
                        "top_left": f"x='{x}+10':y='{y}+10'",
                        "top_center": f"x='{x}+({w}-text_w)/2':y='{y}+10'",
                        "top_right": f"x='{x}+{w}-text_w-10':y='{y}+10'",
                        "center_left": f"x='{x}+10':y='{y}+({h}-text_h)/2'",
                        "center": f"x='{x}+({w}-text_w)/2':y='{y}+({h}-text_h)/2'",
                        "center_right": f"x='{x}+{w}-text_w-10':y='{y}+({h}-text_h)/2'",
                        "bottom_left": f"x='{x}+10':y='{y}+{h}-text_h-10'",
                        "bottom_center": f"x='{x}+({w}-text_w)/2':y='{y}+{h}-text_h-10'",
                        "bottom_right": f"x='{x}+{w}-text_w-10':y='{y}+{h}-text_h-10'",
                    }
                    pos = inner_pos_map.get("center", inner_pos_map["center"])
                else:
                    # User chose a specific position on the video frame
                    screen_pos_map = {
                        "top_left": "x=10:y=10",
                        "top_center": "x=(w-text_w)/2:y=10",
                        "top_right": "x=w-text_w-10:y=10",
                        "center_left": "x=10:y=(h-text_h)/2",
                        "center": "x=(w-text_w)/2:y=(h-text_h)/2",
                        "center_right": "x=w-text_w-10:y=(h-text_h)/2",
                        "bottom_left": "x=10:y=h-text_h-10",
                        "bottom_center": "x=(w-text_w)/2:y=h-text_h-10",
                        "bottom_right": "x=w-text_w-10:y=h-text_h-10",
                    }
                    pos = screen_pos_map.get(replace_position, screen_pos_map["bottom_right"])

                fontfile = self._get_fontfile(font_family, font_style)
                self._video_filters.append(
                    _build_drawtext_filter(
                        text=text,
                        font_size=font_size,
                        color=color,
                        text_opacity=text_opacity,
                        font_style=font_style,
                        font_family=font_family,
                        background_enabled=background_enabled,
                        background_color=background_color,
                        background_style=background_style,
                        background_opacity=background_opacity,
                        pos=pos,
                        fontfile=fontfile,
                    )
                )

    def build_video_filter(self) -> str:
        if not self._video_filters:
            return ""

        filters = list(self._video_filters)

        def is_complex(f: str) -> bool:
            return ";" in f or "movie=" in f or "overlay=" in f or "[logo_scaled]" in f or "[logo_s]" in f

        segments = []
        current_linear = []

        for f in filters:
            if is_complex(f):
                if current_linear:
                    segments.append(("linear", current_linear))
                    current_linear = []
                segments.append(("complex", f))
            else:
                current_linear.append(f)

        if current_linear:
            segments.append(("linear", current_linear))

        if len(segments) == 1 and segments[0][0] == "linear":
            chain = ["format=yuv420p"] + segments[0][1]
            return ",".join(chain)

        graph_parts = []
        current_stream = "[in]"
        stream_counter = 1
        format_added = False

        for idx, (seg_type, seg_content) in enumerate(segments):
            is_last = (idx == len(segments) - 1)

            if seg_type == "linear":
                linear_items = list(seg_content)
                if not format_added:
                    linear_items = ["format=yuv420p"] + linear_items
                    format_added = True
                chain = ",".join(linear_items)

                if is_last:
                    graph_parts.append(f"{current_stream}{chain}")
                else:
                    out_stream = f"[v{stream_counter}]"
                    stream_counter += 1
                    graph_parts.append(f"{current_stream}{chain}{out_stream}")
                    current_stream = out_stream

            else:  # complex
                cf_str = seg_content
                if not format_added:
                    init_stream = f"[v{stream_counter}]"
                    stream_counter += 1
                    graph_parts.append(f"{current_stream}format=yuv420p{init_stream}")
                    current_stream = init_stream
                    format_added = True

                if "[in]" in cf_str:
                    cf_str = cf_str.replace("[in]", current_stream)

                if is_last:
                    graph_parts.append(cf_str)
                else:
                    out_stream = f"[v{stream_counter}]"
                    stream_counter += 1
                    graph_parts.append(f"{cf_str}{out_stream}")
                    current_stream = out_stream

        return ";".join(graph_parts)

    def build_audio_filter(self) -> str:
        return ",".join(self._audio_filters)

    def _get_random_or_fixed(
        self, config: Dict[str, Any], key: str, default: float, range_vals: List[float]
    ) -> float:
        if config.get("randomize", False):
            return round(random.uniform(range_vals[0], range_vals[1]), 3)
        return config.get(key, default)
