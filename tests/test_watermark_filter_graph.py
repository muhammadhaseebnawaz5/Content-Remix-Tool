import os
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtWidgets import QApplication

from src.ffmpeg.filter_graph import FilterGraph
from src.ui.main_window import MainWindow

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_add_only_mode_skips_inpainting_and_adds_overlay():
    graph = FilterGraph()
    graph.add_watermark(
        {
            "enabled": True,
            "mode": "add_only",
            "content_type": "text",
            "text": "Hello",
            "position": "top_left",
            "opacity": 0.7,
        }
    )

    rendered = graph.build_video_filter()

    assert "drawtext=text='Hello'" in rendered
    assert "delogo=" not in rendered
    assert "movie=" not in rendered


def test_remove_replace_mode_inpaints_then_replaces(tmp_path: Path):
    logo_path = tmp_path / "logo.png"
    logo_path.write_bytes(b"fake-logo")

    graph = FilterGraph()
    graph.add_watermark(
        {
            "enabled": True,
            "mode": "remove_replace",
            "removal_method": "replace",
            "content_type": "logo",
            "logo_path": str(logo_path),
            "box": [10, 20, 30, 40],
            "position": "bottom_right",
            "opacity": 0.6,
        }
    )

    rendered = graph.build_video_filter()

    assert "delogo=x=10:y=20:w=30:h=40" in rendered
    assert "movie='" in rendered
    assert "overlay=x=10:y=20" in rendered


def test_add_only_mode_applies_text_style_background_and_opacity():
    graph = FilterGraph()
    graph.add_watermark(
        {
            "enabled": True,
            "mode": "add_only",
            "content_type": "text",
            "text": "Hello",
            "position": "top_left",
            "opacity": 0.7,
            "font_style": "Bold Italic",
            "font_family": "Arial",
            "text_opacity": 0.35,
            "background_enabled": True,
            "background_color": "#123456",
            "background_style": "Rounded Box",
            "background_opacity": 0.6,
        }
    )

    rendered = graph.build_video_filter()

    assert "font='Arial Bold Italic'" in rendered
    assert "fontcolor=#FFFFFF@0.35" in rendered
    assert "box=1:boxcolor=#123456@0.60" in rendered


def test_watermark_background_controls_enable_for_text_mode():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    window._watermark_check.setChecked(True)
    window._watermark_mode_add_only.setChecked(True)
    window._watermark_content_text.setChecked(True)
    window._watermark_background_enable.setChecked(True)
    window._on_watermark_mode_changed()

    assert window._watermark_background_controls.isEnabled()
    assert window._watermark_background_color_btn.isEnabled()

    window._watermark_content_logo.setChecked(True)
    window._on_watermark_mode_changed()

    assert not window._watermark_background_controls.isEnabled()
    assert not window._watermark_background_color_btn.isEnabled()

    app.quit()


def test_zoom_uses_selected_zoom_level():
    graph = FilterGraph()
    media_info = SimpleNamespace(
        video_streams=[SimpleNamespace(width=1920, height=1080, fps=30, duration=5)]
    )

    graph.add_zoom({"mode": "zoom_in", "zoom_level": 1.5}, media_info)

    rendered = graph.build_video_filter()

    assert "crop=1280:720:320:180,scale=1920:1080" in rendered


def test_camera_shake_uses_percentage_based_displacement():
    graph = FilterGraph()
    media_info = SimpleNamespace(
        video_streams=[SimpleNamespace(width=1000, height=600, fps=30, duration=5)]
    )

    graph.add_camera_shake({"intensity": 0.5}, media_info)

    rendered = graph.build_video_filter()

    assert "crop=iw-5:ih-3:random(0)*5:random(0)*3,scale=iw:ih" in rendered


def test_zoom_level_control_accepts_manual_input_and_updates_label():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    window._apply_zoom_level_value("1.15")

    assert window._zoom_level_label_value.text() == "1.15x"

    window._apply_zoom_level_value("2.5")
    assert window._zoom_level_label_value.text() == "2.0x"

    app.quit()


def test_animated_zoom_modes_show_range_controls():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    window._tabs.setCurrentIndex(1)
    window.show()
    QApplication.processEvents()

    window._zoom_mode.setCurrentText("dynamic")
    window._update_zoom_controls_visibility()

    assert window._zoom_range_from.isVisible()
    assert window._zoom_range_to.isVisible()

    window._zoom_mode.setCurrentText("zoom_in")
    window._update_zoom_controls_visibility()

    assert not window._zoom_range_from.isVisible()
    assert not window._zoom_range_to.isVisible()

    app.quit()


def test_watermark_center_positions_are_mapped():
    graph = FilterGraph()
    graph.add_watermark(
        {
            "enabled": True,
            "mode": "add_only",
            "content_type": "text",
            "text": "Hello",
            "position": "center_left",
            "opacity": 0.7,
        }
    )

    rendered = graph.build_video_filter()

    assert "x=10:y=(h-text_h)/2" in rendered


def test_remove_replace_logo_with_non_box_position_and_geometry_effect(tmp_path: Path):
    logo_path = tmp_path / "logo.png"
    logo_path.write_bytes(b"fake-logo")

    graph = FilterGraph()
    effects = {
        "watermark": {
            "enabled": True,
            "mode": "remove_replace",
            "removal_method": "replace",
            "content_type": "logo",
            "replace_logo_path": str(logo_path),
            "replace_position": "top_right",
            "box": [10, 20, 30, 40],
            "opacity": 0.8,
        },
        "mirror": {"enabled": True, "mode": "horizontal"},
        "crop": {"enabled": True, "aspect_ratio": "16:9", "mode": "center"},
    }
    stream = SimpleNamespace(width=1920, height=1080)
    media_info = SimpleNamespace(width=1920, height=1080, video_streams=[stream])
    graph.configure(effects, media_info=media_info)
    rendered = graph.build_video_filter()

    assert "delogo=x=10:y=20:w=30:h=40" in rendered
    assert "movie='" in rendered
    assert "scale2ref=w='min(max(main_w*0.14" in rendered
    assert "overlay=x=W-w-10:y=10" in rendered
    assert "hflip" in rendered
    assert "crop=" in rendered
    assert ",[in]" not in rendered

