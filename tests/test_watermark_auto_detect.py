import numpy as np

from src.ffmpeg.filter_graph import FilterGraph
from src.ffmpeg.watermark_removal import find_watermark_box, auto_remove_watermark


def test_find_watermark_box_detects_bottom_right_saturated_blob():
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    frame[140:, 190:] = (30, 200, 255)
    frame[150:, 200:] = (20, 180, 245)

    box = find_watermark_box(frame)

    assert box is not None
    x, y, w, h = box
    assert x >= 180
    assert y >= 120
    assert w > 0 and h > 0


def test_find_watermark_box_detects_logo_outside_lower_right_corner():
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    frame[20:80, 25:110] = (10, 180, 255)

    box = find_watermark_box(frame)

    assert box is not None
    x, y, w, h = box
    assert x < 150
    assert y < 120
    assert w > 0 and h > 0


def test_filter_graph_uses_replace_logo_position_and_path(tmp_path):
    graph = FilterGraph()
    logo_path = tmp_path / "logo.png"
    logo_path.write_bytes(b"not-a-real-image")

    graph.add_watermark(
        {
            "mode": "remove_replace",
            "removal_method": "replace",
            "content_type": "logo",
            "replace_logo_path": str(logo_path),
            "replace_position": "bottom_right",
            "replace_opacity": 0.8,
            "box": [20, 30, 80, 60],
            "opacity": 0.8,
        }
    )

    result = graph.build_video_filter()

    assert "overlay=" in result
    assert "logo_scaled" in result
    assert "movie='" in result
    assert "x=20:y=30" in result or "overlay=x=20:y=30" in result


def test_auto_remove_watermark_uses_manual_box_when_detection_fails(
    monkeypatch, tmp_path
):
    video_path = tmp_path / "video.mp4"
    out_path = tmp_path / "output.mp4"
    video_path.write_bytes(b"fake")

    class FakeCapture:
        def __init__(self, path):
            self._path = path

        def isOpened(self):
            return True

        def read(self):
            return True, np.zeros((120, 160, 3), dtype=np.uint8)

        def release(self):
            pass

    monkeypatch.setattr("cv2.VideoCapture", lambda path: FakeCapture(path))
    monkeypatch.setattr("builtins.input", lambda prompt="": "10,20,30,40")

    calls = {}

    def fake_remove(video_path_arg, output_path_arg, box):
        calls["args"] = (str(video_path_arg), str(output_path_arg), tuple(box))
        return output_path_arg

    monkeypatch.setattr(
        "src.ffmpeg.watermark_removal.remove_watermark",
        fake_remove,
    )

    result = auto_remove_watermark(str(video_path), str(out_path))

    assert result == (10, 20, 30, 40)
    assert calls["args"][0] == str(video_path)
    assert calls["args"][1] == str(out_path)
