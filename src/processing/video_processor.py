"""
VideoProcessor - Processes a single video with retry logic and graceful error handling.
"""

import os
import shutil
import time
from typing import Dict, Any, Optional, Callable
from ..ffmpeg.probe import Probe
from ..ffmpeg.command_builder import CommandBuilder
from ..ffmpeg.ffmpeg_engine import FFmpegEngine, FFmpegResult


class VideoProcessor:
    """Handles single video processing with retries and FFmpeg validation."""

    def __init__(self, ffmpeg_path: str = "ffmpeg"):
        self._ffmpeg_path = ffmpeg_path
        self._engine = FFmpegEngine(ffmpeg_path)
        self._builder = CommandBuilder(ffmpeg_path)
        self._probe = Probe()
        self._ffmpeg_available = shutil.which(ffmpeg_path) is not None

    def is_ready(self) -> bool:
        """Check if FFmpeg is available."""
        return self._ffmpeg_available

    def process(self, input_path: str, output_path: str, config: Dict[str, Any],
                progress_callback: Optional[Callable] = None,
                gpu_encoders: Optional[list] = None) -> FFmpegResult:
        """Process a single video."""
        if not self._ffmpeg_available:
            return FFmpegResult(success=False, error_message="FFmpeg not found in PATH")

        if not os.path.exists(input_path):
            return FFmpegResult(success=False, error_message=f"Input file not found: {input_path}")

        media_info = self._probe.analyze(input_path)
        duration = media_info.duration if media_info else 0

        if progress_callback:
            self._engine.set_progress_callback(progress_callback)

        temp_inpainted: Optional[str] = None
        actual_input = input_path
        try:
            wm_cfg = config.get("effects", {}).get("watermark", {})
            if (
                wm_cfg.get("enabled")
                and wm_cfg.get("mode") == "remove_replace"
                and wm_cfg.get("removal_quality") == "inpaint"
            ):
                box = wm_cfg.get("box")
                if (
                    box
                    and isinstance(box, (list, tuple))
                    and len(box) == 4
                    and box[2] > 0
                    and box[3] > 0
                ):
                    from ..ffmpeg.watermark_removal import inpaint_watermark
                    temp_inpainted = output_path + ".inpainted.mp4"
                    inpaint_watermark(input_path, temp_inpainted, box)
                    actual_input = temp_inpainted

            # First attempt with configured encoder
            cmd = self._builder.build(actual_input, output_path, config, media_info, gpu_encoders)
            cmd_str = self._builder.get_command_string(cmd)
            print(f"[FFmpeg CMD] {cmd_str}")

            self._engine._cancelled = False
            result = self._engine.execute(cmd, duration)

            # If failed and GPU encoder was used, fallback to CPU encoder
            if not result.success and gpu_encoders:
                current_encoder = config.get("export", {}).get("encoder", "")
                if current_encoder in gpu_encoders and current_encoder != "libx264":
                    print(f"[FFmpeg FALLBACK] GPU encoder failed, trying libx264...")
                    fallback_config = dict(config)
                    fallback_config["export"] = dict(config.get("export", {}))
                    fallback_config["export"]["encoder"] = "libx264"
                    fallback_config["processing"] = dict(config.get("processing", {}))
                    fallback_config["processing"]["gpu_acceleration"] = False

                    cmd2 = self._builder.build(actual_input, output_path, fallback_config, media_info, [])
                    cmd_str2 = self._builder.get_command_string(cmd2)
                    print(f"[FFmpeg CMD FALLBACK] {cmd_str2}")

                    result2 = self._engine.execute(cmd2, duration)
                    if result2.success:
                        return result2
                    # Return original error if fallback also fails
                    result.error_message = f"GPU encoder failed: {result.error_message}\nFallback also failed: {result2.error_message}"

            if not result.success:
                result.error_message = f"Command: {cmd_str}\nError: {result.error_message}"

            return result
        except Exception as e:
            return FFmpegResult(success=False, error_message=str(e))
        finally:
            if temp_inpainted and os.path.exists(temp_inpainted):
                try:
                    os.remove(temp_inpainted)
                except OSError:
                    pass

    def process_with_retry(self, input_path: str, output_path: str, config: Dict[str, Any],
                           max_retries: int = 3,
                           progress_callback: Optional[Callable] = None,
                           gpu_encoders: Optional[list] = None) -> FFmpegResult:
        """Process with automatic retry on failure."""
        if not self._ffmpeg_available:
            return FFmpegResult(success=False, error_message="FFmpeg not found in PATH")

        last_result = None
        for attempt in range(max_retries):
            last_result = self.process(input_path, output_path, config, progress_callback, gpu_encoders)
            if last_result.success:
                return last_result
            if attempt < max_retries - 1:
                time.sleep(min(2 ** attempt, 10))
        return last_result if last_result else FFmpegResult(success=False, error_message="All retries failed")

    def cancel(self) -> None:
        """Cancel current processing."""
        self._engine.cancel()
