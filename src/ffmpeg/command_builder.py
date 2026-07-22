"""
CommandBuilder - Builds complete FFmpeg command lines.
Uses simple -vf / -af approach for maximum reliability.
"""

import os
import subprocess
import shutil
from typing import List, Dict, Any, Optional
from .filter_graph import FilterGraph
from .probe import Probe


class CommandBuilder:
    """Constructs FFmpeg commands using -vf and -af (reliable approach)."""

    GPU_ENCODER_MAP = {
        "nvidia": {"h264": "h264_nvenc", "hevc": "hevc_nvenc", "av1": "av1_nvenc"},
        "intel": {"h264": "h264_qsv", "hevc": "hevc_qsv", "av1": None},
        "amd": {"h264": "h264_amf", "hevc": "hevc_amf", "av1": None}
    }

    # Simplified, compatible presets
    GPU_PRESETS = {
        "h264_nvenc": ["-preset", "fast", "-rc", "vbr", "-b:v", "0"],
        "hevc_nvenc": ["-preset", "fast", "-rc", "vbr", "-b:v", "0"],
        "av1_nvenc":  ["-preset", "fast", "-rc", "vbr", "-b:v", "0"],
        "h264_qsv":   ["-preset", "fast", "-global_quality", "23"],
        "hevc_qsv":   ["-preset", "fast", "-global_quality", "23"],
        "h264_amf":   ["-quality", "speed", "-rc", "vbr"],
        "hevc_amf":   ["-quality", "speed", "-rc", "vbr"],
    }

    RESOLUTION_MAP = {
        "720p": (1280, 720),
        "1080p": (1920, 1080),
        "2K": (2560, 1440),
        "4K": (3840, 2160)
    }

    def __init__(self, ffmpeg_path: str = "ffmpeg"):
        self._ffmpeg = ffmpeg_path
        self._probe = Probe()
        self._gpu_encoders: List[str] = []

    def detect_gpu_encoders(self) -> List[str]:
        """Detect available GPU encoders by testing ffmpeg."""
        encoders = []
        test_encoders = [
            "h264_nvenc", "hevc_nvenc", "av1_nvenc",
            "h264_qsv", "hevc_qsv",
            "h264_amf", "hevc_amf"
        ]
        for enc in test_encoders:
            try:
                cmd = [self._ffmpeg, "-f", "lavfi", "-i", "nullsrc=duration=0.1", "-c:v", enc, "-frames:v", "1", "-f", "null", "-"]
                result = subprocess.run(cmd, capture_output=True, timeout=10)
                stderr = result.stderr.decode('utf-8', errors='ignore').lower()
                if "unknown encoder" not in stderr and "not found" not in stderr:
                    encoders.append(enc)
            except Exception:
                pass
        self._gpu_encoders = encoders
        return encoders

    def build(self, input_path: str, output_path: str, config: Dict[str, Any],
              media_info: Optional[Any] = None, gpu_encoders: Optional[List[str]] = None) -> List[str]:
        """Build complete FFmpeg command using -vf and -af."""
        if gpu_encoders is None:
            gpu_encoders = self._gpu_encoders

        if media_info is None:
            media_info = self._probe.analyze(input_path)

        cmd = [self._ffmpeg, "-y"]

        # Input
        cmd.extend(["-i", input_path])

        # Build filters
        filter_graph = FilterGraph()
        filter_graph.configure(config.get("effects", {}), media_info)

        video_filters = filter_graph.build_video_filter()
        audio_filters = filter_graph.build_audio_filter()

        # Resolution scaling (append to video filter chain)
        export_cfg = config.get("export", {})
        resolution = export_cfg.get("resolution", "original")
        scale_filter = None

        if resolution == "Original (Min 720p)":
            if media_info and media_info.video_streams:
                orig_h = media_info.video_streams[0].height
                if 0 < orig_h < 720:
                    scale_filter = "scale=-2:720:flags=lanczos"
        elif resolution != "original" and resolution in self.RESOLUTION_MAP:
            w, h = self.RESOLUTION_MAP[resolution]
            scale_filter = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black"

        if scale_filter:
            if video_filters:
                video_filters += f",{scale_filter}"
            else:
                video_filters = scale_filter

        # Apply video filters via -vf
        if video_filters:
            cmd.append("-vf")
            cmd.append(video_filters)

        # Apply audio filters via -af
        if audio_filters:
            cmd.append("-af")
            cmd.append(audio_filters)

        # Encoder selection
        encoder = export_cfg.get("encoder", "libx264")
        if encoder in gpu_encoders:
            cmd.extend(["-c:v", encoder])
            preset = self.GPU_PRESETS.get(encoder, [])
            cmd.extend(preset)
        else:
            cmd.extend(["-c:v", encoder])
            if encoder.startswith("libx"):
                cmd.extend(["-preset", "fast", "-crf", str(config.get("video", {}).get("crf", 23))])

        # Video settings
        bitrate = export_cfg.get("bitrate", "5M")
        fps = export_cfg.get("fps", 30)
        cmd.extend(["-b:v", bitrate, "-r", str(fps)])

        # Audio codec (copy if no audio filters, else re-encode)
        if audio_filters:
            cmd.extend(["-c:a", "aac", "-b:a", "192k"])
        else:
            cmd.extend(["-c:a", "copy"])

        # Pixel format
        cmd.extend(["-pix_fmt", "yuv420p"])

        # Movflags for fast start (web-friendly)
        cmd.extend(["-movflags", "+faststart"])

        # Output
        cmd.append(output_path)
        return cmd

    def build_concat_command(self, inputs: List[str], output_path: str, config: Dict[str, Any]) -> List[str]:
        """Build command to concatenate multiple videos using concat demuxer."""
        # Use concat demuxer file approach
        concat_file = output_path + ".concat.txt"
        with open(concat_file, "w", encoding="utf-8") as f:
            for inp in inputs:
                # Escape single quotes in path
                safe_path = inp.replace("'", "'\\''")
                f.write(f"file '{safe_path}'\n")

        cmd = [
            self._ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", concat_file,
            "-c", "copy",
            output_path
        ]
        return cmd

    def build_simple_command(self, input_path: str, output_path: str, video_filter: str) -> List[str]:
        """Build simple single-filter command."""
        cmd = [
            self._ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-i", input_path,
            "-vf", video_filter,
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "copy",
            "-pix_fmt", "yuv420p",
            output_path
        ]
        return cmd

    def build_thumbnail_command(self, input_path: str, output_path: str, time_sec: float = 1.0) -> List[str]:
        """Build thumbnail extraction command."""
        return [
            self._ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-ss", str(time_sec),
            "-i", input_path,
            "-vframes", "1", "-q:v", "2",
            output_path
        ]

    def get_command_string(self, cmd: List[str]) -> str:
        """Get command as string for logging."""
        return " ".join(f'"{arg}"' if " " in arg or ";" in arg or "," in arg else arg for arg in cmd)
