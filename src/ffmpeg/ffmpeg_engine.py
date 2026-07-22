"""
FFmpegEngine - Runs FFmpeg process, tracks progress, supports pause/resume/cancel.
"""

import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Optional, Callable, List
from .probe import Probe


@dataclass
class FFmpegProgress:
    frame: int = 0
    fps: float = 0.0
    bitrate: str = ""
    time_sec: float = 0.0
    percent: float = 0.0
    speed: str = ""


@dataclass
class FFmpegResult:
    success: bool = False
    return_code: int = -1
    error_message: str = ""
    encoding_time_sec: float = 0.0
    output_size_bytes: int = 0
    command: str = ""
    stderr_output: str = ""


class FFmpegEngine:
    """Executes FFmpeg commands with progress tracking and controls."""

    def __init__(self, ffmpeg_path: str = "ffmpeg"):
        self._ffmpeg = ffmpeg_path
        self._process: Optional[subprocess.Popen] = None
        self._cancelled = False
        self._paused = False
        self._pause_event = threading.Event()
        self._pause_event.set()
        self._progress_callback: Optional[Callable[[FFmpegProgress], None]] = None
        self._probe = Probe()

    def set_progress_callback(self, callback: Callable[[FFmpegProgress], None]) -> None:
        self._progress_callback = callback

    def execute(self, cmd: List[str], duration_sec: float = 0.0) -> FFmpegResult:
        """Execute FFmpeg command with progress tracking."""
        self._cancelled = False
        self._paused = False
        self._pause_event.set()
        start_time = time.time()

        result = FFmpegResult()
        result.command = " ".join(f'"{a}"' if " " in a else a for a in cmd)

        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE,
                text=True,
                bufsize=1,
                universal_newlines=True,
                encoding="utf-8",
                errors="ignore"
            )
        except Exception as e:
            result.error_message = str(e)
            return result

        progress = FFmpegProgress()
        error_lines: List[str] = []
        all_output: List[str] = []

        def read_output():
            if self._process is None or self._process.stdout is None:
                return
            for line in self._process.stdout:
                line = line.strip()
                if not line:
                    continue
                all_output.append(line)
                # Parse progress
                if line.startswith("frame=") or line.startswith("size="):
                    self._pause_event.wait()
                    if self._cancelled:
                        break
                    parsed = self._parse_progress_line(line)
                    if parsed:
                        progress.frame = parsed.get("frame", 0)
                        progress.fps = parsed.get("fps", 0.0)
                        progress.bitrate = parsed.get("bitrate", "")
                        progress.time_sec = parsed.get("time_sec", 0.0)
                        progress.speed = parsed.get("speed", "")
                        if duration_sec > 0:
                            progress.percent = min(100.0, (progress.time_sec / duration_sec) * 100)
                        if self._progress_callback:
                            self._progress_callback(progress)
                elif "error" in line.lower() or "failed" in line.lower() or "invalid" in line.lower():
                    error_lines.append(line)

        reader_thread = threading.Thread(target=read_output, daemon=True)
        reader_thread.start()

        try:
            return_code = self._process.wait()
        except Exception as e:
            result.error_message = str(e)
            return result

        reader_thread.join(timeout=5.0)
        elapsed = time.time() - start_time

        output_path = cmd[-1] if cmd else ""
        output_size = 0
        if output_path and os.path.exists(output_path):
            output_size = os.path.getsize(output_path)

        success = (return_code == 0) and not self._cancelled
        error_msg = "\n".join(error_lines[-10:]) if error_lines else ""
        if self._cancelled:
            error_msg = "Cancelled by user"
            success = False

        # If failed, include more output for debugging
        stderr_full = "\n".join(all_output[-30:]) if all_output else ""

        return FFmpegResult(
            success=success,
            return_code=return_code,
            error_message=error_msg or (stderr_full if not success else ""),
            encoding_time_sec=elapsed,
            output_size_bytes=output_size,
            command=result.command,
            stderr_output=stderr_full
        )

    def cancel(self) -> None:
        """Kill the FFmpeg process."""
        self._cancelled = True
        self._pause_event.set()
        if self._process and self._process.poll() is None:
            try:
                self._process.terminate()
                time.sleep(0.5)
                if self._process.poll() is None:
                    self._process.kill()
            except Exception:
                pass

    def pause(self) -> None:
        self._paused = True
        self._pause_event.clear()

    def resume(self) -> None:
        self._paused = False
        self._pause_event.set()

    def analyze(self, path: str):
        return self._probe.analyze(path)

    @staticmethod
    def _parse_progress_line(line: str) -> Optional[dict]:
        """Parse FFmpeg progress output line."""
        result = {}
        frame_match = re.search(r"frame=\s*(\d+)", line)
        if frame_match:
            result["frame"] = int(frame_match.group(1))

        fps_match = re.search(r"fps=\s*([\d.]+)", line)
        if fps_match:
            result["fps"] = float(fps_match.group(1))

        bitrate_match = re.search(r"bitrate=\s*([\d.]+\w+/s)", line)
        if bitrate_match:
            result["bitrate"] = bitrate_match.group(1)

        time_match = re.search(r"time=(\d+):(\d+):(\d+[.]?\d*)", line)
        if time_match:
            h = int(time_match.group(1))
            m = int(time_match.group(2))
            s = float(time_match.group(3))
            result["time_sec"] = h * 3600 + m * 60 + s

        speed_match = re.search(r"speed=\s*([\d.]+x)", line)
        if speed_match:
            result["speed"] = speed_match.group(1)

        size_match = re.search(r"size=\s*(\d+\w+)", line)
        if size_match:
            result["size"] = size_match.group(1)

        return result if result else None
