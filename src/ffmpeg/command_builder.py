"""
CommandBuilder - Builds complete FFmpeg command lines.
Uses simple -vf / -af approach for maximum reliability.
"""

import os
import random
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

        music = self._plan_music(config, media_info, filter_graph.speed_factor, audio_filters)
        if music:
            cmd.extend(music["input_args"])

        # Apply video filters via -vf
        if video_filters:
            cmd.append("-vf")
            cmd.append(video_filters)

        if music:
            cmd.extend(["-filter_complex", music["filter_complex"]])
            cmd.extend(["-map", "0:v:0", "-map", music["audio_label"]])
            cmd.extend(music["output_args"])
        elif audio_filters:
            # Apply audio filters via -af
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
        if audio_filters or music:
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

    def _plan_music(
        self,
        config: Dict[str, Any],
        media_info: Optional[Any],
        speed_factor: float,
        audio_filters: str,
    ) -> Optional[Dict[str, Any]]:
        """Prepare FFmpeg inputs and filters for optional background music."""
        music_config = config.get("audio", {}).get("background_music", {})
        track = music_config.get("file", "")
        if (
            not music_config.get("enabled")
            or not track
            or not os.path.isfile(track)
        ):
            return None

        volume = max(0.0, min(2.0, float(music_config.get("volume", 0.5))))
        fade_in = max(0.0, float(music_config.get("fade_in", 0.5)))
        fade_out = max(0.0, float(music_config.get("fade_out", 1.5)))
        mode = music_config.get("mode", "replace")
        original_volume = max(
            0.0, min(2.0, float(music_config.get("original_volume", 0.5)))
        )
        random_start = bool(music_config.get("random_start", False))
        music_duration = max(0.0, float(music_config.get("music_duration", 0.0)))

        video_duration = max(0.0, float(getattr(media_info, "duration", 0.0) or 0.0))
        output_duration = (
            video_duration / speed_factor
            if video_duration > 0 and speed_factor > 0
            else 0.0
        )

        input_args: List[str] = []
        if output_duration > 0 and music_duration >= output_duration:
            start = 0.0
            if random_start and music_duration > output_duration:
                start = random.uniform(0.0, music_duration - output_duration)
            if start > 0:
                input_args.extend(["-ss", f"{start:.2f}"])
            input_args.extend(["-i", track])
        else:
            input_args.extend(["-stream_loop", "-1", "-i", track])

        music_filters = [
            "aresample=44100",
            "aformat=channel_layouts=stereo",
            f"volume={volume:.3f}",
        ]
        if fade_in > 0:
            music_filters.append(f"afade=t=in:st=0:d={fade_in:.2f}")
        if fade_out > 0 and output_duration > fade_out:
            music_filters.append(
                f"afade=t=out:st={output_duration - fade_out:.2f}:d={fade_out:.2f}"
            )
        music_chain = "[1:a]" + ",".join(music_filters) + "[m]"

        has_original_audio = bool(getattr(media_info, "audio_streams", None))
        if mode == "mix" and has_original_audio:
            original_filters = [f"volume={original_volume:.3f}"]
            if audio_filters:
                original_filters.append(audio_filters)
            original_filters.extend(
                ["aresample=44100", "aformat=channel_layouts=stereo"]
            )
            filter_complex = (
                f"[0:a]{','.join(original_filters)}[o];{music_chain};"
                "[o][m]amix=inputs=2:duration=first:dropout_transition=0:"
                "normalize=0[aout]"
            )
            audio_label = "[aout]"
        else:
            filter_complex = music_chain
            audio_label = "[m]"

        output_args = (
            ["-t", f"{output_duration:.3f}"]
            if output_duration > 0
            else ["-shortest"]
        )
        return {
            "input_args": input_args,
            "filter_complex": filter_complex,
            "audio_label": audio_label,
            "output_args": output_args,
        }

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
