"""Automatic watermark detection and removal using OpenCV + FFmpeg."""

import os
import re
import subprocess
from typing import Optional, Tuple

import cv2
import numpy as np


def find_watermark_box(frame) -> Optional[Tuple[int, int, int, int]]:
    """Detect the watermark box in a video frame.

    Watermarks are often placed in the corners, but they can also appear in the
    center or on the left/top edge. The detector therefore scans the full frame,
    with a lower-right bias for speed, and falls back to a full-frame mask when
    a corner-based detection does not find anything.
    """
    if frame is None or frame.size == 0:
        return None

    height, width = frame.shape[:2]
    if height <= 0 or width <= 0:
        return None

    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    saturation = hsv[:, :, 1]
    value = hsv[:, :, 2]

    # Look for vivid logo/text pixels while keeping the detector permissive
    # enough to catch watermarks in any corner or even centered overlays.
    mask = ((saturation >= 60) & (value >= 80)).astype(np.uint8) * 255

    roi_masks = []
    if width > 0 and height > 0:
        roi = np.zeros_like(mask)
        roi[height // 2 :, width // 2 :] = 255
        roi_masks.append(roi)
        roi = np.zeros_like(mask)
        roi[height // 3 :, width // 3 :] = 255
        roi_masks.append(roi)
        roi_masks.append(np.ones_like(mask))

    best_box = None
    best_area = 0
    for roi in roi_masks:
        candidate = cv2.bitwise_and(mask, roi)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        candidate = cv2.morphologyEx(candidate, cv2.MORPH_OPEN, kernel)
        candidate = cv2.morphologyEx(candidate, cv2.MORPH_CLOSE, kernel)

        contours, _ = cv2.findContours(
            candidate, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        if not contours:
            continue

        largest = max(contours, key=cv2.contourArea)
        area = cv2.contourArea(largest)
        min_area = max(400, int(0.0006 * width * height))
        if area < min_area:
            continue

        x, y, w, h = cv2.boundingRect(largest)
        if w <= 0 or h <= 0:
            continue

        if area > best_area:
            best_area = area
            best_box = (x, y, w, h)

    if best_box is None:
        return None

    x, y, w, h = best_box
    padding_x = max(3, int(w * 0.04))
    padding_y = max(3, int(h * 0.04))
    x = max(0, x - padding_x)
    y = max(0, y - padding_y)
    w = min(width - x, w + (padding_x * 2))
    h = min(height - y, h + (padding_y * 2))

    return int(x), int(y), int(w), int(h)


def remove_watermark(video_path: str, output_path: str, box) -> str:
    """Remove a watermark region using FFmpeg delogo with a padded box."""
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Input video not found: {video_path}")

    if box is None:
        raise ValueError("Watermark box is required for removal.")

    x, y, w, h = [int(v) for v in box]
    if w <= 0 or h <= 0:
        raise ValueError(f"Invalid watermark box: {box}")

    # Expand the box slightly to cover anti-aliased edges and transparent
    # borders without pushing the box too far away from the detection result.
    pad_x = max(4, int(w * 0.08))
    pad_y = max(4, int(h * 0.08))
    x = max(0, x - pad_x)
    y = max(0, y - pad_y)

    # Read metadata once for safe clamping against the input frame size.
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Unable to open video: {video_path}")
    frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()

    if frame_width > 0:
        x = min(x, max(0, frame_width - 1))
        w = min(w + (pad_x * 2), max(1, frame_width - x))
    if frame_height > 0:
        y = min(y, max(0, frame_height - 1))
        h = min(h + (pad_y * 2), max(1, frame_height - y))

    ffmpeg_path = "ffmpeg"
    cmd = [
        ffmpeg_path,
        "-y",
        "-i",
        video_path,
        "-vf",
        f"delogo=x={x}:y={y}:w={w}:h={h}:show=0",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        output_path,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        stderr = result.stderr.strip() or result.stdout.strip() or "ffmpeg failed"
        raise RuntimeError(f"FFmpeg watermark removal failed: {stderr}")

    return output_path


def inpaint_watermark(video_path: str, output_path: str, box) -> str:
    """Remove a watermark region using OpenCV frame-by-frame inpainting for high quality."""
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Input video not found: {video_path}")

    if box is None:
        raise ValueError("Watermark box is required for inpainting.")

    x, y, w, h = [int(v) for v in box]
    if w <= 0 or h <= 0:
        raise ValueError(f"Invalid watermark box: {box}")

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Unable to open video: {video_path}")

    frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

    # Expand/pad box slightly to cover edges
    pad_x = max(3, int(w * 0.05))
    pad_y = max(3, int(h * 0.05))
    x = max(0, x - pad_x)
    y = max(0, y - pad_y)
    w = min(frame_width - x, w + (pad_x * 2))
    h = min(frame_height - y, h + (pad_y * 2))

    mask = np.zeros((frame_height, frame_width), dtype=np.uint8)
    mask[y : y + h, x : x + w] = 255

    temp_video = output_path + ".temp_inpaint.mp4"
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(temp_video, fourcc, fps, (frame_width, frame_height))

    try:
        while True:
            ret, frame = cap.read()
            if not ret or frame is None:
                break
            inpainted = cv2.inpaint(frame, mask, inpaintRadius=3, flags=cv2.INPAINT_TELEA)
            out.write(inpainted)
    finally:
        cap.release()
        out.release()

    ffmpeg_path = "ffmpeg"
    cmd = [
        ffmpeg_path,
        "-y",
        "-i",
        temp_video,
        "-i",
        video_path,
        "-c:v",
        "libx264",
        "-c:a",
        "copy",
        "-map",
        "0:v:0",
        "-map",
        "1:a:0?",
        "-pix_fmt",
        "yuv420p",
        output_path,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if os.path.exists(temp_video):
        try:
            os.remove(temp_video)
        except OSError:
            pass

    if result.returncode != 0:
        if os.path.exists(temp_video):
            import shutil
            shutil.move(temp_video, output_path)

    return output_path


def auto_remove_watermark(video_path: str, output_path: str):
    """Auto-detect the watermark box from the first frame and remove it.

    If detection fails, the user is prompted to enter a manual box in the form
    X,Y,W,H, which is then used for removal.
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Input video not found: {video_path}")

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Unable to open video: {video_path}")

    ret, frame = cap.read()
    cap.release()
    if not ret or frame is None:
        raise RuntimeError(f"Unable to read first frame from: {video_path}")

    box = find_watermark_box(frame)
    if box is None:
        print(
            "Automatic watermark detection failed. Please enter manual box as X,Y,W,H."
        )
        manual = input("Watermark box (X,Y,W,H): ").strip()
        values = re.split(r"[\s,]+", manual)
        if len(values) != 4:
            raise ValueError("Invalid manual box input. Expected X,Y,W,H.")
        try:
            box = tuple(int(float(v)) for v in values)
        except ValueError as exc:
            raise ValueError("Manual box must contain four integers.") from exc

    remove_watermark(video_path, output_path, box)
    return box


__all__ = [
    "find_watermark_box",
    "remove_watermark",
    "inpaint_watermark",
    "auto_remove_watermark",
]

