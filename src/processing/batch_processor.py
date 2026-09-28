"""
BatchProcessor - Parallel video processing using ThreadPoolExecutor.
Robust error handling and state management.
"""

import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor, Future
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Callable
from copy import deepcopy

from ..core.event_bus import get_event_bus, EventBus
from ..utils.randomizer import Randomizer
from .video_processor import VideoProcessor
from ..ffmpeg.ffmpeg_engine import FFmpegResult


@dataclass
class BatchProgress:
    total: int = 0
    completed: int = 0
    failed: int = 0
    skipped: int = 0
    percent: float = 0.0
    elapsed_sec: float = 0.0
    estimated_remaining_sec: float = 0.0
    speed: float = 0.0
    current_file: str = ""


@dataclass
class BatchResult:
    successful: int = 0
    failed: int = 0
    skipped: int = 0
    total_time_sec: float = 0.0
    results: List[Dict[str, Any]] = field(default_factory=list)
    failed_videos: List[str] = field(default_factory=list)


class BatchProcessor:
    """Manages parallel batch video processing with full state control."""

    STATE_IDLE = "idle"
    STATE_RUNNING = "running"
    STATE_PAUSED = "paused"
    STATE_COMPLETED = "completed"
    STATE_ERROR = "error"
    STATE_CANCELLING = "cancelling"

    def __init__(self, max_workers: int = 4, ffmpeg_path: str = "ffmpeg"):
        self._max_workers = max_workers
        self._ffmpeg_path = ffmpeg_path
        self._state = self.STATE_IDLE
        self._executor: Optional[ThreadPoolExecutor] = None
        self._futures: List[Future] = []
        self._cancelled = False
        self._paused = False
        self._pause_event = threading.Event()
        self._pause_event.set()
        self._progress = BatchProgress()
        self._results: List[Dict[str, Any]] = []
        self._failed_videos: List[str] = []
        self._event_bus = get_event_bus()
        self._randomizer = Randomizer()
        self._gpu_encoders: List[str] = []
        self._start_time = 0.0
        self._lock = threading.Lock()

    def set_gpu_encoders(self, encoders: List[str]) -> None:
        self._gpu_encoders = encoders

    def start(self, files: List[str], output_dir: str, config: Dict[str, Any],
              prefix: str = "", suffix: str = "") -> None:
        """Start batch processing."""
        if self._state == self.STATE_RUNNING:
            return

        self._state = self.STATE_RUNNING
        self._cancelled = False
        self._paused = False
        self._pause_event.set()
        self._progress = BatchProgress(total=len(files))
        self._results = []
        self._failed_videos = []
        self._start_time = time.time()

        os.makedirs(output_dir, exist_ok=True)

        self._executor = ThreadPoolExecutor(max_workers=self._max_workers)
        self._futures = []

        for index, file_path in enumerate(files):
            if self._cancelled:
                break

            base_name = os.path.splitext(os.path.basename(file_path))[0]
            out_name = f"{prefix}{base_name}{suffix}.mp4"
            out_path = os.path.join(output_dir, out_name)

            counter = 1
            while os.path.exists(out_path):
                out_name = f"{prefix}{base_name}{suffix}_{counter}.mp4"
                out_path = os.path.join(output_dir, out_name)
                counter += 1

            file_config = deepcopy(config)
            self._randomizer.apply_randomization(file_config, index)
            if file_config.get("ai_remix", {}).get("duplicate_prevention", False):
                self._randomizer.apply_forced_variation(file_config.setdefault("effects", {}))

            future = self._executor.submit(
                self._process_single,
                file_path,
                out_path,
                file_config,
                index
            )
            self._futures.append(future)

        monitor = threading.Thread(target=self._monitor_completion, args=(len(files),), daemon=True)
        monitor.start()

        self._event_bus.emit(EventBus.PROCESSING_STARTED, {
            "total": len(files),
            "output_dir": output_dir
        })

    def _process_single(self, input_path: str, output_path: str, config: Dict[str, Any], index: int) -> Dict[str, Any]:
        while self._paused and not self._cancelled:
            time.sleep(0.2)

        if self._cancelled:
            return {"input": input_path, "output": output_path, "success": False, "reason": "cancelled", "index": index}

        self._event_bus.emit(EventBus.VIDEO_STARTED, {
            "index": index,
            "input": input_path,
            "output": output_path
        })

        processor = VideoProcessor(self._ffmpeg_path)
        if not processor.is_ready():
            return {
                "index": index,
                "input": input_path,
                "output": output_path,
                "success": False,
                "reason": "ffmpeg_missing",
                "error": "FFmpeg not found in PATH",
                "encoding_time": 0
            }

        def on_progress(p):
            with self._lock:
                self._progress.current_file = os.path.basename(input_path)
            self._event_bus.emit(EventBus.PROCESSING_PROGRESS, {
                "index": index,
                "file": os.path.basename(input_path),
                "percent": p.percent,
                "fps": p.fps,
                "speed": p.speed
            })

        result = processor.process_with_retry(
            input_path, output_path, config,
            max_retries=config.get("processing", {}).get("max_retries", 3),
            progress_callback=on_progress,
            gpu_encoders=self._gpu_encoders
        )

        info = {
            "index": index,
            "input": input_path,
            "output": output_path,
            "success": result.success,
            "encoding_time": result.encoding_time_sec,
            "output_size": result.output_size_bytes,
            "error": result.error_message,
            "command": result.command,
            "stderr": result.stderr_output
        }

        if result.success:
            self._event_bus.emit(EventBus.VIDEO_COMPLETED, info)
        else:
            self._event_bus.emit(EventBus.VIDEO_FAILED, info)

        return info

    def _monitor_completion(self, total_files: int) -> None:
        completed = 0
        failed = 0
        skipped = 0

        for future in self._futures:
            try:
                info = future.result(timeout=3600)
                self._results.append(info)
                if info.get("success"):
                    completed += 1
                elif info.get("reason") in ("cancelled", "ffmpeg_missing"):
                    skipped += 1
                else:
                    failed += 1
                    self._failed_videos.append(info.get("input", ""))
            except Exception as e:
                failed += 1
                self._results.append({"success": False, "error": str(e)})

            with self._lock:
                self._progress.completed = completed
                self._progress.failed = failed
                self._progress.skipped = skipped
                if self._progress.total > 0:
                    self._progress.percent = ((completed + failed + skipped) / self._progress.total) * 100

                elapsed = time.time() - self._start_time
                self._progress.elapsed_sec = elapsed
                processed = completed + failed + skipped
                if processed > 0 and elapsed > 0:
                    self._progress.speed = (processed / elapsed) * 60
                    remaining = self._progress.total - processed
                    self._progress.estimated_remaining_sec = (remaining / processed) * elapsed

        if self._executor:
            self._executor.shutdown(wait=False)
            self._executor = None

        if self._cancelled:
            self._state = self.STATE_CANCELLING
        elif failed > 0 and completed == 0:
            self._state = self.STATE_ERROR
        else:
            self._state = self.STATE_COMPLETED

        batch_result = BatchResult(
            successful=completed,
            failed=failed,
            skipped=skipped,
            total_time_sec=time.time() - self._start_time,
            results=self._results,
            failed_videos=self._failed_videos
        )

        self._event_bus.emit(EventBus.PROCESSING_COMPLETED, {
            "result": batch_result,
            "state": self._state
        })

    def pause(self) -> None:
        if self._state == self.STATE_RUNNING:
            self._paused = True
            self._pause_event.clear()
            self._state = self.STATE_PAUSED
            self._event_bus.emit(EventBus.PROCESSING_PAUSED)

    def resume(self) -> None:
        if self._state == self.STATE_PAUSED:
            self._paused = False
            self._pause_event.set()
            self._state = self.STATE_RUNNING
            self._event_bus.emit(EventBus.PROCESSING_RESUMED)

    def cancel(self) -> None:
        self._cancelled = True
        self._paused = False
        self._pause_event.set()
        self._state = self.STATE_CANCELLING
        for future in self._futures:
            future.cancel()
        self._event_bus.emit(EventBus.PROCESSING_CANCELLED)

    def set_workers(self, n: int) -> None:
        self._max_workers = max(1, n)

    def get_progress(self) -> BatchProgress:
        with self._lock:
            return BatchProgress(
                total=self._progress.total,
                completed=self._progress.completed,
                failed=self._progress.failed,
                skipped=self._progress.skipped,
                percent=self._progress.percent,
                elapsed_sec=self._progress.elapsed_sec,
                estimated_remaining_sec=self._progress.estimated_remaining_sec,
                speed=self._progress.speed,
                current_file=self._progress.current_file
            )

    @property
    def state(self) -> str:
        return self._state
