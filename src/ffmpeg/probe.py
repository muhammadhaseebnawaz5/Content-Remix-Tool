"""
Probe - ffprobe wrapper for video metadata extraction.
Fallback to OpenCV if ffprobe is unavailable.
"""

import subprocess
import json
import os
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional


@dataclass
class VideoStreamInfo:
    codec: str = ""
    width: int = 0
    height: int = 0
    fps: float = 0.0
    bitrate: int = 0
    duration: float = 0.0
    frame_count: int = 0
    pixel_format: str = ""


@dataclass
class AudioStreamInfo:
    codec: str = ""
    sample_rate: int = 0
    channels: int = 0
    bitrate: int = 0
    language: str = ""


@dataclass
class MediaInfo:
    file_path: str = ""
    duration: float = 0.0
    bitrate: int = 0
    format_name: str = ""
    video_streams: List[VideoStreamInfo] = field(default_factory=list)
    audio_streams: List[AudioStreamInfo] = field(default_factory=list)


class Probe:
    """Video/Audio metadata analyzer using ffprobe."""

    SUPPORTED_FORMATS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".ts", ".flv", ".wmv"}

    def __init__(self, ffprobe_path: str = "ffprobe"):
        self._ffprobe = ffprobe_path

    def analyze(self, file_path: str) -> MediaInfo:
        """Analyze media file and return MediaInfo."""
        if not os.path.exists(file_path):
            return MediaInfo(file_path=file_path)

        try:
            cmd = [
                self._ffprobe,
                "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                "-show_streams",
                file_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode != 0:
                return self._fallback_analyze(file_path)

            data = json.loads(result.stdout)
            return self._parse_probe_data(file_path, data)
        except Exception:
            return self._fallback_analyze(file_path)

    def _parse_probe_data(self, file_path: str, data: Dict[str, Any]) -> MediaInfo:
        """Parse ffprobe JSON output."""
        fmt = data.get("format", {})
        streams = data.get("streams", [])

        info = MediaInfo(
            file_path=file_path,
            duration=float(fmt.get("duration", 0)),
            bitrate=int(fmt.get("bit_rate", 0)),
            format_name=fmt.get("format_name", "")
        )

        for stream in streams:
            codec_type = stream.get("codec_type")
            if codec_type == "video":
                fps_str = stream.get("r_frame_rate", "0/1")
                try:
                    num, den = map(int, fps_str.split("/"))
                    fps = num / den if den != 0 else 0
                except Exception:
                    fps = 0.0

                duration = info.duration
                frame_count = int(stream.get("nb_frames", 0))
                if frame_count == 0 and duration > 0 and fps > 0:
                    frame_count = int(duration * fps)

                info.video_streams.append(VideoStreamInfo(
                    codec=stream.get("codec_name", ""),
                    width=stream.get("width", 0),
                    height=stream.get("height", 0),
                    fps=fps,
                    bitrate=int(stream.get("bit_rate", 0)),
                    duration=duration,
                    frame_count=frame_count,
                    pixel_format=stream.get("pix_fmt", "")
                ))
            elif codec_type == "audio":
                info.audio_streams.append(AudioStreamInfo(
                    codec=stream.get("codec_name", ""),
                    sample_rate=int(stream.get("sample_rate", 0)),
                    channels=stream.get("channels", 0),
                    bitrate=int(stream.get("bit_rate", 0)),
                    language=stream.get("tags", {}).get("language", "")
                ))

        return info

    def get_simple_info(self, file_path: str) -> Dict[str, Any]:
        """Return simplified metadata dict for UI display."""
        info = self.analyze(file_path)
        if not info.video_streams:
            return {"path": file_path, "error": "No video stream found"}
        v = info.video_streams[0]
        return {
            "path": file_path,
            "filename": os.path.basename(file_path),
            "duration": round(info.duration, 2),
            "duration_str": self._seconds_to_time(info.duration),
            "resolution": f"{v.width}x{v.height}",
            "fps": round(v.fps, 2),
            "codec": v.codec,
            "bitrate": self._human_readable_bitrate(info.bitrate),
            "size": self._human_readable_size(os.path.getsize(file_path)) if os.path.exists(file_path) else "N/A"
        }

    def is_supported_format(self, path: str) -> bool:
        """Check if file extension is supported."""
        ext = os.path.splitext(path)[1].lower()
        return ext in self.SUPPORTED_FORMATS

    def _fallback_analyze(self, file_path: str) -> MediaInfo:
        """Fallback analysis using OpenCV."""
        try:
            import cv2
            cap = cv2.VideoCapture(file_path)
            if not cap.isOpened():
                return MediaInfo(file_path=file_path)

            fps = cap.get(cv2.CAP_PROP_FPS)
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            duration = frame_count / fps if fps > 0 else 0
            cap.release()

            return MediaInfo(
                file_path=file_path,
                duration=duration,
                video_streams=[VideoStreamInfo(
                    width=width,
                    height=height,
                    fps=fps,
                    duration=duration,
                    frame_count=frame_count
                )]
            )
        except Exception:
            return MediaInfo(file_path=file_path)

    @staticmethod
    def _seconds_to_time(seconds: float) -> str:
        """Convert seconds to HH:MM:SS."""
        secs = int(seconds)
        h = secs // 3600
        m = (secs % 3600) // 60
        s = secs % 60
        return f"{h:02d}:{m:02d}:{s:02d}"

    @staticmethod
    def _human_readable_bitrate(bitrate: int) -> str:
        """Convert bps to human readable."""
        if bitrate >= 1_000_000:
            return f"{bitrate / 1_000_000:.2f} Mbps"
        elif bitrate >= 1_000:
            return f"{bitrate / 1_000:.2f} kbps"
        return f"{bitrate} bps"

    @staticmethod
    def _human_readable_size(size_bytes: int) -> str:
        """Convert bytes to human readable."""
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size_bytes < 1024.0:
                return f"{size_bytes:.2f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.2f} PB"
