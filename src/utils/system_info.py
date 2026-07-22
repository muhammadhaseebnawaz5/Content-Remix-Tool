"""
SystemInfo - Detects hardware and software capabilities.
"""

import os
import platform
import subprocess
import sys
from typing import Dict, Any, List, Optional


class SystemInfo:
    """Detects system hardware and software info."""

    def __init__(self):
        self._info: Optional[Dict[str, Any]] = None

    def get_info(self) -> Dict[str, Any]:
        """Get system information."""
        if self._info is not None:
            return self._info

        self._info = {
            "cpu": self._detect_cpu(),
            "ram_gb": self._detect_ram(),
            "gpu": self._detect_gpu(),
            "gpu_vram": None,
            "cuda_version": None,
            "ffmpeg_version": self._detect_ffmpeg(),
            "python_version": sys.version.split()[0],
            "os": platform.platform(),
            "libraries": self._detect_libraries()
        }
        return self._info

    def recommended_workers(self) -> int:
        """Recommend worker count based on hardware."""
        try:
            import multiprocessing
            cores = multiprocessing.cpu_count()
        except Exception:
            cores = 4

        gpu = self._detect_gpu()
        if gpu and "none" not in gpu.lower():
            return min(cores * 2, 16)
        return max(1, min(cores, 8))

    def _detect_cpu(self) -> str:
        try:
            if platform.system() == "Windows":
                result = subprocess.run(["wmic", "cpu", "get", "name"], capture_output=True, text=True)
                lines = [l.strip() for l in result.stdout.split("\n") if l.strip() and "Name" not in l]
                return lines[0] if lines else platform.processor()
            else:
                with open("/proc/cpuinfo", "r") as f:
                    for line in f:
                        if line.startswith("model name"):
                            return line.split(":", 1)[1].strip()
        except Exception:
            pass
        return platform.processor() or "Unknown"

    def _detect_ram(self) -> float:
        try:
            import psutil
            return round(psutil.virtual_memory().total / (1024**3), 1)
        except Exception:
            pass
        try:
            if platform.system() == "Windows":
                result = subprocess.run(["wmic", "computersystem", "get", "totalphysicalmemory"], capture_output=True, text=True)
                lines = [l.strip() for l in result.stdout.split("\n") if l.strip() and "TotalPhysicalMemory" not in l]
                if lines:
                    return round(int(lines[0]) / (1024**3), 1)
            else:
                with open("/proc/meminfo", "r") as f:
                    for line in f:
                        if line.startswith("MemTotal:"):
                            kb = int(line.split()[1])
                            return round(kb / (1024**2), 1)
        except Exception:
            pass
        return 0.0

    def _detect_gpu(self) -> str:
        """Detect GPU using nvidia-smi or other methods."""
        try:
            result = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                                    capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                line = result.stdout.strip().split("\n")[0]
                parts = [p.strip() for p in line.split(",")]
                if parts:
                    return parts[0]
        except Exception:
            pass

        # Try torch
        try:
            import torch
            if torch.cuda.is_available():
                return torch.cuda.get_device_name(0)
        except Exception:
            pass

        return "None detected"

    def _detect_ffmpeg(self) -> str:
        try:
            result = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                first = result.stdout.split("\n")[0]
                return first.replace("ffmpeg version ", "").split()[0]
        except Exception:
            pass
        return "Not found"

    def _detect_libraries(self) -> Dict[str, str]:
        libs = {}
        for lib in ["cv2", "torch", "onnxruntime", "whisper", "PySide6"]:
            try:
                __import__(lib)
                libs[lib] = "installed"
            except ImportError:
                libs[lib] = "not installed"
        return libs
