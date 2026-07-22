"""
File utilities - path generation, safe rename, disk space check.
"""

import os
import shutil
from typing import Optional


def ensure_dir(path: str) -> str:
    """Ensure directory exists."""
    os.makedirs(path, exist_ok=True)
    return path


def safe_rename(src: str, dst: str) -> str:
    """Rename file, handling duplicates."""
    if not os.path.exists(dst):
        os.rename(src, dst)
        return dst
    base, ext = os.path.splitext(dst)
    counter = 1
    while True:
        new_dst = f"{base}_{counter}{ext}"
        if not os.path.exists(new_dst):
            os.rename(src, new_dst)
            return new_dst
        counter += 1


def get_available_space(path: str) -> int:
    """Get available disk space in bytes."""
    return shutil.disk_usage(path).free


def human_readable_size(size_bytes: int) -> str:
    """Convert bytes to human readable."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(size_bytes) < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"


def get_unique_output_path(directory: str, filename: str) -> str:
    """Get a unique output path, adding counter if needed."""
    path = os.path.join(directory, filename)
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(filename)
    counter = 1
    while True:
        new_name = f"{base}_{counter}{ext}"
        new_path = os.path.join(directory, new_name)
        if not os.path.exists(new_path):
            return new_path
        counter += 1
