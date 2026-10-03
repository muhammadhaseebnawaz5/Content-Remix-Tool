"""
MainWindow - Professional PySide6 main application window.
Tabs: Sources, Effects, Export, Processing, Monitor.

Thread-safe design: All UI updates happen on the main thread via QTimer polling.
Worker threads only write to thread-safe data structures.
"""

import os
import sys
import queue
import threading
from datetime import datetime
from typing import Optional, List, Dict, Any

from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTabWidget,
    QToolButton,
    QLabel,
    QPushButton,
    QLineEdit,
    QComboBox,
    QSpinBox,
    QDoubleSpinBox,
    QCheckBox,
    QGroupBox,
    QListWidget,
    QTableWidget,
    QTableWidgetItem,
    QProgressBar,
    QTextEdit,
    QFileDialog,
    QMessageBox,
    QHeaderView,
    QSlider,
    QSplitter,
    QFrame,
    QSizePolicy,
    QScrollArea,
    QGridLayout,
    QFormLayout,
    QMenuBar,
    QMenu,
    QStatusBar,
    QApplication,
    QLayout,
    QRadioButton,
    QButtonGroup,
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QRubberBand,
)
from PySide6.QtCore import Qt, QTimer, QSize, QThread, Signal, QPoint, QRect
from PySide6.QtGui import QAction, QFont, QColor, QPixmap, QImage

from ..core.event_bus import get_event_bus, EventBus
from ..core.project_manager import ProjectManager
from ..core.config_manager import ConfigManager


class WatermarkROIDialog(QDialog):
    """Qt-native watermark region selector.

    Displays the video frame scaled to fit the screen so the selection
    controls are never cut off.  The user click-drags a rubber-band
    rectangle; on accept the selection is back-transformed to original
    video pixel coordinates.
    """

    # Maximum preview dimensions (fit within common screen sizes)
    MAX_W = 1200
    MAX_H = 700

    def __init__(self, frame_bgr, parent=None):
        super().__init__(parent)
        self.setWindowTitle(
            "Draw a box around the watermark  —  click & drag, then click OK"
        )
        self.setModal(True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        import cv2
        import numpy as np

        # Convert BGR (OpenCV) → RGB → QPixmap
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        orig_h, orig_w = rgb.shape[:2]
        self._orig_w = orig_w
        self._orig_h = orig_h

        # Scale factor so the preview fits inside MAX_W × MAX_H
        scale = min(self.MAX_W / max(orig_w, 1), self.MAX_H / max(orig_h, 1), 1.0)
        disp_w = max(1, int(orig_w * scale))
        disp_h = max(1, int(orig_h * scale))
        self._scale = scale

        scaled = cv2.resize(rgb, (disp_w, disp_h), interpolation=cv2.INTER_AREA)
        qimage = QImage(
            scaled.data, disp_w, disp_h, disp_w * 3, QImage.Format.Format_RGB888
        )
        pixmap = QPixmap.fromImage(qimage)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        hint = QLabel(
            "ℹ  Click and drag to draw a rectangle around the watermark area."
        )
        hint.setObjectName("subheading")
        layout.addWidget(hint)

        self._canvas = _ROICanvas(pixmap, self)
        layout.addWidget(self._canvas)

        self._status = QLabel("No selection")
        self._status.setObjectName("subheading")
        layout.addWidget(self._status)
        self._canvas.selection_changed.connect(self._update_status)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.setMinimumSize(disp_w + 20, disp_h + 120)

    def _update_status(self, rect: QRect) -> None:
        if rect.isNull() or rect.isEmpty():
            self._status.setText("No selection")
        else:
            # Back-transform to original video coordinates
            x, y, w, h = self._video_box(rect)
            self._status.setText(f"Selected: x={x}, y={y}, w={w}, h={h} (video pixels)")

    def _video_box(self, rect: QRect):
        """Convert display-coordinate QRect to original video pixel coords."""
        s = self._scale
        x = max(0, int(rect.x() / s))
        y = max(0, int(rect.y() / s))
        w = min(self._orig_w - x, max(1, int(rect.width() / s)))
        h = min(self._orig_h - y, max(1, int(rect.height() / s)))
        return x, y, w, h

    def get_selection(self):
        """Return (x, y, w, h) in original video pixels, or None."""
        rect = self._canvas.selection_rect()
        if rect is None or rect.isNull() or rect.isEmpty():
            return None
        return self._video_box(rect)


class _ROICanvas(QLabel):
    """Canvas that renders a pixmap and lets the user draw a rubber-band box."""

    selection_changed = Signal(QRect)

    def __init__(self, pixmap: QPixmap, parent=None):
        super().__init__(parent)
        self.setPixmap(pixmap)
        self.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._rubber = QRubberBand(QRubberBand.Shape.Rectangle, self)
        self._origin: Optional[QPoint] = None
        self._rect: Optional[QRect] = None

    def selection_rect(self) -> Optional[QRect]:
        return self._rect

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._origin = event.pos()
            self._rubber.setGeometry(QRect(self._origin, QSize()))
            self._rubber.show()

    def mouseMoveEvent(self, event):
        if self._origin is not None:
            r = QRect(self._origin, event.pos()).normalized()
            self._rubber.setGeometry(r)
            self._rect = r
            self.selection_changed.emit(r)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._origin is not None:
            r = QRect(self._origin, event.pos()).normalized()
            self._rubber.setGeometry(r)
            self._rect = r
            self._origin = None
            self.selection_changed.emit(r)

from ..core.settings_manager import SettingsManager
from ..processing.batch_processor import BatchProcessor, BatchProgress
from ..io.scanner import Scanner
from ..utils.system_info import SystemInfo
from ..utils.logger import setup_logger
from .theme import Theme


class FFmpegCheckThread(QThread):
    """Background thread to check FFmpeg availability."""

    result_ready = Signal(bool, str)

    def run(self):
        import shutil
        import subprocess

        ffmpeg_path = shutil.which("ffmpeg")
        ffprobe_path = shutil.which("ffprobe")
        if ffmpeg_path and ffprobe_path:
            try:
                result = subprocess.run(
                    ["ffmpeg", "-version"], capture_output=True, text=True, timeout=5
                )
                version = (
                    result.stdout.split("\n")[0]
                    .replace("ffmpeg version ", "")
                    .split()[0]
                    if result.stdout
                    else "unknown"
                )
                self.result_ready.emit(True, version)
            except Exception:
                self.result_ready.emit(False, "Error checking FFmpeg")
        else:
            missing = []
            if not ffmpeg_path:
                missing.append("ffmpeg")
            if not ffprobe_path:
                missing.append("ffprobe")
            self.result_ready.emit(False, f"Missing: {', '.join(missing)}")


class ZoomLevelComboBox(QComboBox):
    """Editable combo box for selecting preset zoom levels or entering custom zoom values."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setEditable(True)
        preset_values = [
            "1.0x",
            "1.1x",
            "1.2x",
            "1.3x",
            "1.4x",
            "1.5x",
            "1.6x",
            "1.7x",
            "1.8x",
            "1.9x",
            "2.0x",
        ]
        self.addItems(preset_values)
        self.setCurrentText("1.2x")

    def value(self) -> float:
        text = self.currentText().replace("x", "").strip()
        try:
            val = float(text)
            return max(1.0, val)
        except ValueError:
            return 1.2

    def setValue(self, val: float | str) -> None:
        try:
            clamped = max(1.0, float(str(val).replace("x", "").strip()))
        except (TypeError, ValueError):
            clamped = 1.2
        disp = round(clamped, 2)
        if abs(disp - round(disp)) < 1e-9:
            formatted = f"{disp:.1f}x"
        else:
            formatted = f"{disp:.2f}".rstrip("0").rstrip(".") + "x"
        idx = self.findText(formatted)
        if idx >= 0:
            self.setCurrentIndex(idx)
        else:
            self.setEditText(formatted)

    def blockSignals(self, b: bool) -> bool:
        line_edit = self.lineEdit()
        if line_edit is not None:
            line_edit.blockSignals(b)
        return super().blockSignals(b)


class MainWindow(QMainWindow):
    """Main application window with thread-safe UI updates."""

    # Signals for cross-thread UI updates (worker -> main thread)
    _sig_processing_started = Signal(dict)
    _sig_processing_progress = Signal(dict)
    _sig_processing_completed = Signal(dict)
    _sig_processing_paused = Signal()
    _sig_processing_resumed = Signal()
    _sig_processing_cancelled = Signal()
    _sig_video_started = Signal(dict)
    _sig_video_completed = Signal(dict)
    _sig_video_failed = Signal(dict)
    _sig_ffmpeg_checked = Signal(bool, str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("AI Bulk Remix Studio")
        self.setMinimumSize(1280, 800)
        self.resize(1600, 1000)

        # Core components
        self._event_bus = get_event_bus()
        self._project = ProjectManager()
        self._config = ConfigManager()
        self._settings = SettingsManager()
        self._scanner = Scanner()
        self._system_info = SystemInfo()
        self._theme = Theme(self._settings.get("theme", "dark"))
        self._batch_processor = BatchProcessor(
            max_workers=self._config.get("processing.max_workers", 4)
        )
        self._logger = setup_logger(
            level="INFO",
            log_dir=os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "logs"
            ),
        )

        # Thread-safe state
        self._source_files: List[str] = []
        self._output_dir = ""
        self._is_processing = False
        self._ffmpeg_available = False
        self._ffmpeg_version = ""
        self._ui_lock = threading.Lock()
        self._latest_progress: Optional[Dict[str, Any]] = None
        self._active_widgets: Dict[int, Dict[str, Any]] = {}

        self._setup_menubar()
        self._setup_ui()
        self._apply_theme()
        self._connect_events()
        self._connect_signals()
        self._detect_hardware()
        self._check_ffmpeg()
        self._start_ui_timer()

        self._logger.info("MainWindow initialized")

    def _setup_menubar(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu("&File")

        new_action = QAction("&New Project", self)
        new_action.setShortcut("Ctrl+N")
        new_action.triggered.connect(self._new_project)
        file_menu.addAction(new_action)

        open_action = QAction("&Open Project...", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self._open_project)
        file_menu.addAction(open_action)

        save_action = QAction("&Save Project", self)
        save_action.setShortcut("Ctrl+S")
        save_action.triggered.connect(self._save_project)
        file_menu.addAction(save_action)

        file_menu.addSeparator()

        exit_action = QAction("E&xit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        tools_menu = menubar.addMenu("&Tools")
        detect_hw = QAction("&Detect Hardware", self)
        detect_hw.triggered.connect(self._detect_hardware)
        tools_menu.addAction(detect_hw)

        help_menu = menubar.addMenu("&Help")
        about_action = QAction("&About", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _setup_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(14)

        # Header
        header = QHBoxLayout()
        header.setSpacing(16)

        title_col = QVBoxLayout()
        title = QLabel("AI Bulk Remix Studio")
        title.setObjectName("heading")
        title_col.addWidget(title)

        subtitle = QLabel("Bulk Video Processing with Duplicate Prevention")
        subtitle.setObjectName("subheading")
        title_col.addWidget(subtitle)
        header.addLayout(title_col)

        header.addStretch()

        self._ffmpeg_status_label = QLabel("Checking FFmpeg...")
        self._ffmpeg_status_label.setObjectName("status_warn")
        header.addWidget(self._ffmpeg_status_label)

        self._theme_btn = QPushButton("Dark")
        self._theme_btn.setToolTip("Toggle Theme")
        self._theme_btn.setFixedSize(50, 32)
        self._theme_btn.setObjectName("tool")
        self._theme_btn.clicked.connect(self._toggle_theme)
        header.addWidget(self._theme_btn)

        layout.addLayout(header)

        divider = QFrame()
        divider.setObjectName("divider")
        divider.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(divider)

        # Tabs
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        layout.addWidget(self._tabs)

        self._tabs.addTab(self._build_sources_tab(), "  Sources  ")
        self._tabs.addTab(self._build_effects_tab(), "  Effects  ")
        self._tabs.addTab(self._build_watermark_tab(), "  Watermark  ")
        self._tabs.addTab(self._build_music_tab(), "  Music  ")
        self._tabs.addTab(self._build_export_tab(), "  Export  ")
        self._tabs.addTab(self._build_processing_tab(), "  Processing  ")
        self._tabs.addTab(self._build_monitor_tab(), "  Monitor  ")

        # Status bar
        self._statusbar = QStatusBar()
        self._statusbar.showMessage("Ready")
        self.setStatusBar(self._statusbar)

    def _build_sources_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(18)

        dir_group = QGroupBox("Input / Output Directories")
        dir_layout = QGridLayout(dir_group)
        dir_layout.setSpacing(12)
        dir_layout.setColumnStretch(1, 1)

        dir_layout.addWidget(QLabel("Input Directory:"), 0, 0)
        self._input_dir_edit = QLineEdit()
        self._input_dir_edit.setPlaceholderText(
            "Select folder containing source videos..."
        )
        dir_layout.addWidget(self._input_dir_edit, 0, 1)

        # Folder browse + Import file buttons side-by-side
        browse_btn_row = QHBoxLayout()
        browse_btn_row.setSpacing(6)
        btn_browse_in = QPushButton("Open Folder")
        btn_browse_in.setObjectName("tool")
        btn_browse_in.setToolTip(
            "Select a folder — all video files inside will be scanned"
        )
        btn_browse_in.clicked.connect(self._browse_input_dir)
        browse_btn_row.addWidget(btn_browse_in)

        btn_import_files = QPushButton("Import File(s)")
        btn_import_files.setObjectName("primary")
        btn_import_files.setToolTip(
            "Pick one or more individual video files to add directly"
        )
        btn_import_files.clicked.connect(self._import_files)
        browse_btn_row.addWidget(btn_import_files)
        dir_layout.addLayout(browse_btn_row, 0, 2)

        dir_layout.addWidget(QLabel("Output Directory:"), 1, 0)
        self._output_dir_edit = QLineEdit()
        self._output_dir_edit.setPlaceholderText(
            "Select folder to save processed videos..."
        )
        dir_layout.addWidget(self._output_dir_edit, 1, 1)
        btn_browse_out = QPushButton("Browse...")
        btn_browse_out.setObjectName("tool")
        btn_browse_out.clicked.connect(self._browse_output_dir)
        dir_layout.addWidget(btn_browse_out, 1, 2)

        self._recursive_check = QCheckBox("Scan subdirectories recursively")
        self._recursive_check.setChecked(False)
        dir_layout.addWidget(self._recursive_check, 2, 0, 1, 2)

        btn_scan = QPushButton("Scan for Videos")
        btn_scan.setObjectName("primary")
        btn_scan.setMinimumHeight(36)
        btn_scan.clicked.connect(self._scan_videos)
        dir_layout.addWidget(btn_scan, 2, 2)

        layout.addWidget(dir_group)

        list_group = QGroupBox("Video Files")
        list_layout = QVBoxLayout(list_group)
        list_layout.setSpacing(10)

        self._file_table = QTableWidget()
        self._file_table.setColumnCount(5)
        self._file_table.setHorizontalHeaderLabels(
            ["Filename", "Duration", "Resolution", "Size", "Status"]
        )
        self._file_table.horizontalHeader().setStretchLastSection(True)
        self._file_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._file_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Fixed
        )
        self._file_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Fixed
        )
        self._file_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Fixed
        )
        self._file_table.setColumnWidth(1, 100)
        self._file_table.setColumnWidth(2, 120)
        self._file_table.setColumnWidth(3, 100)
        self._file_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._file_table.setAlternatingRowColors(True)
        self._file_table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        list_layout.addWidget(self._file_table)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        btn_remove = QPushButton("Remove Selected")
        btn_remove.setObjectName("danger")
        btn_remove.clicked.connect(self._remove_selected_files)
        btn_row.addWidget(btn_remove)

        btn_clear = QPushButton("Clear All")
        btn_clear.setObjectName("tool")
        btn_clear.clicked.connect(self._clear_files)
        btn_row.addWidget(btn_clear)

        list_layout.addLayout(btn_row)
        layout.addWidget(list_group)

        self._source_stats = QLabel("0 videos selected")
        self._source_stats.setObjectName("subheading")
        layout.addWidget(self._source_stats)

        layout.addStretch()
        return tab

    def _build_effects_tab(self) -> QWidget:
        tab = QScrollArea()
        tab.setWidgetResizable(True)
        tab.setFrameShape(QFrame.Shape.NoFrame)
        container = QWidget()
        container.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.MinimumExpanding
        )
        layout = QVBoxLayout(container)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinAndMaxSize)
        layout.setSpacing(18)

        ai_group = QGroupBox("AI Remix - Duplicate Prevention Engine")
        ai_layout = QVBoxLayout(ai_group)
        ai_layout.setSpacing(10)

        ai_desc = QLabel(
            "Automatically randomizes effects per video so each output has a unique fingerprint. This helps avoid duplicate content penalties on social platforms."
        )
        ai_desc.setWordWrap(True)
        ai_desc.setObjectName("subheading")
        ai_layout.addWidget(ai_desc)

        self._ai_remix_check = QCheckBox("Enable AI Remix / Randomization")
        self._ai_remix_check.setChecked(True)
        ai_layout.addWidget(self._ai_remix_check)

        self._dup_prevent_check = QCheckBox(
            "Strict Duplicate Prevention (force-enable extra effects to reach minimum)"
        )
        self._dup_prevent_check.setChecked(True)
        ai_layout.addWidget(self._dup_prevent_check)

        # Minimum effects spinbox (configurable, was hardcoded to 3)
        min_vary_row = QHBoxLayout()
        min_vary_row.setSpacing(8)
        min_vary_row.addWidget(QLabel("  Min. effects that must vary per video:"))
        self._min_effects_vary_spin = QSpinBox()
        self._min_effects_vary_spin.setRange(1, 6)
        self._min_effects_vary_spin.setValue(3)
        self._min_effects_vary_spin.setToolTip(
            "When Duplicate Prevention is ON, if fewer than this many effects are\n"
            "being randomised, the app will ask your permission before auto-enabling\n"
            "extra colour effects (Brightness / Contrast / Saturation / Hue /\n"
            "Sharpness / Noise) to reach this count."
        )
        self._min_effects_vary_spin.setFixedWidth(60)
        min_vary_row.addWidget(self._min_effects_vary_spin)
        min_vary_lbl = QLabel("(app will ask before auto-enabling extra effects)")
        min_vary_lbl.setObjectName("subheading")
        min_vary_row.addWidget(min_vary_lbl)
        min_vary_row.addStretch()
        self._dup_prevent_check.toggled.connect(
            lambda checked: self._min_effects_vary_spin.setEnabled(checked)
        )
        ai_layout.addLayout(min_vary_row)
        layout.addWidget(ai_group)

        trans_group = QGroupBox("Transform Effects")
        trans_layout = QGridLayout(trans_group)
        trans_layout.setSpacing(12)

        self._mirror_check = QCheckBox("Mirror")
        trans_layout.addWidget(self._mirror_check, 0, 0)
        self._mirror_mode = QComboBox()
        self._mirror_mode.addItems(["horizontal", "vertical", "both", "alternate"])
        trans_layout.addWidget(self._mirror_mode, 0, 1)

        self._flip_check = QCheckBox("Flip")
        trans_layout.addWidget(self._flip_check, 0, 2)
        self._flip_mode = QComboBox()
        self._flip_mode.addItems(["horizontal", "vertical"])
        trans_layout.addWidget(self._flip_mode, 0, 3)

        self._rotate_check = QCheckBox("Rotation")
        trans_layout.addWidget(self._rotate_check, 1, 0)
        self._rotate_mode = QComboBox()
        self._rotate_mode.addItems(
            ["small", "large", "clockwise", "anticlockwise", "random"]
        )
        trans_layout.addWidget(self._rotate_mode, 1, 1)

        self._zoom_check = QCheckBox("Zoom")
        trans_layout.addWidget(self._zoom_check, 1, 2)

        zoom_controls_container = QWidget()
        zoom_controls_layout = QHBoxLayout(zoom_controls_container)
        zoom_controls_layout.setContentsMargins(0, 0, 0, 0)
        zoom_controls_layout.setSpacing(6)

        self._zoom_mode = QComboBox()
        self._zoom_mode.addItems(["zoom_in", "zoom_out", "dynamic", "ken_burns"])
        self._zoom_mode.currentTextChanged.connect(
            self._update_zoom_controls_visibility
        )
        zoom_controls_layout.addWidget(self._zoom_mode)

        self._zoom_level_label = QLabel("Zoom Level:")
        zoom_controls_layout.addWidget(self._zoom_level_label)

        self._zoom_level = ZoomLevelComboBox()
        self._zoom_level.currentTextChanged.connect(self._on_zoom_level_changed)
        zoom_controls_layout.addWidget(self._zoom_level)

        self._zoom_level_minus = QPushButton("-")
        self._zoom_level_minus.setFixedWidth(26)
        self._zoom_level_minus.clicked.connect(self._step_zoom_level_down)
        zoom_controls_layout.addWidget(self._zoom_level_minus)

        self._zoom_level_plus = QPushButton("+")
        self._zoom_level_plus.setFixedWidth(26)
        self._zoom_level_plus.clicked.connect(self._step_zoom_level_up)
        zoom_controls_layout.addWidget(self._zoom_level_plus)

        self._zoom_level_label_value = QLabel("1.2x")
        self._zoom_level_label_value.setObjectName("subheading")
        zoom_controls_layout.addWidget(self._zoom_level_label_value)

        trans_layout.addWidget(zoom_controls_container, 1, 3)

        self._zoom_range_from_label = QLabel("From:")
        trans_layout.addWidget(self._zoom_range_from_label, 2, 0)

        self._zoom_range_from = QDoubleSpinBox()
        self._zoom_range_from.setRange(1.0, 2.0)
        self._zoom_range_from.setSingleStep(0.1)
        self._zoom_range_from.setValue(1.0)
        self._zoom_range_from.setDecimals(2)
        self._zoom_range_from.setSuffix("x")
        self._zoom_range_from.setKeyboardTracking(False)
        trans_layout.addWidget(self._zoom_range_from, 2, 1)

        self._zoom_range_to_label = QLabel("To:")
        trans_layout.addWidget(self._zoom_range_to_label, 2, 2)

        self._zoom_range_to = QDoubleSpinBox()
        self._zoom_range_to.setRange(1.0, 2.0)
        self._zoom_range_to.setSingleStep(0.1)
        self._zoom_range_to.setValue(1.3)
        self._zoom_range_to.setDecimals(2)
        self._zoom_range_to.setSuffix("x")
        self._zoom_range_to.setKeyboardTracking(False)
        trans_layout.addWidget(self._zoom_range_to, 2, 3)

        self._update_zoom_level_display(self._zoom_level.value())
        self._update_zoom_controls_visibility(self._zoom_mode.currentText())

        self._crop_check = QCheckBox("Crop")
        trans_layout.addWidget(self._crop_check, 3, 0)
        self._crop_mode = QComboBox()
        self._crop_mode.addItems(["center", "random"])
        trans_layout.addWidget(self._crop_mode, 3, 1)
        trans_layout.addWidget(QLabel("Aspect:"), 3, 2)
        self._crop_aspect = QComboBox()
        self._crop_aspect.addItems(["16:9", "4:3", "1:1", "9:16", "3:2"])
        trans_layout.addWidget(self._crop_aspect, 3, 3)

        self._speed_check = QCheckBox("Speed Change")
        trans_layout.addWidget(self._speed_check, 4, 0)
        self._speed_mode = QComboBox()
        self._speed_mode.addItems(["0.8x", "0.9x", "1.1x", "1.2x", "random"])
        trans_layout.addWidget(self._speed_mode, 4, 1)

        self._shake_check = QCheckBox("Camera Shake")
        trans_layout.addWidget(self._shake_check, 4, 2)
        self._shake_mode = QComboBox()
        self._shake_mode.addItems(
            ["0%", "0.25%", "0.5%", "0.75%", "1.0%", "1.5%", "2.0%"]
        )
        self._shake_mode.setCurrentText("0.5%")
        trans_layout.addWidget(self._shake_mode, 4, 3)
        self._shake_help = QLabel("Higher % = more shake/jitter effect.")
        self._shake_help.setObjectName("subheading")
        trans_layout.addWidget(self._shake_help, 5, 2, 1, 2)

        self._update_zoom_level_display(self._zoom_level.value())
        self._update_zoom_controls_visibility(self._zoom_mode.currentText())

        self._crop_check = QCheckBox("Crop")
        trans_layout.addWidget(self._crop_check, 3, 0)
        self._crop_mode = QComboBox()
        self._crop_mode.addItems(["center", "random"])
        trans_layout.addWidget(self._crop_mode, 3, 1)
        trans_layout.addWidget(QLabel("Aspect:"), 3, 2)
        self._crop_aspect = QComboBox()
        self._crop_aspect.addItems(["16:9", "4:3", "1:1", "9:16", "3:2"])
        trans_layout.addWidget(self._crop_aspect, 3, 3)

        self._speed_check = QCheckBox("Speed Change")
        trans_layout.addWidget(self._speed_check, 4, 0)
        self._speed_mode = QComboBox()
        self._speed_mode.addItems(["0.8x", "0.9x", "1.1x", "1.2x", "random"])
        trans_layout.addWidget(self._speed_mode, 4, 1)

        self._shake_check = QCheckBox("Camera Shake")
        trans_layout.addWidget(self._shake_check, 4, 2)
        self._shake_mode = QComboBox()
        self._shake_mode.addItems(
            ["0%", "0.25%", "0.5%", "0.75%", "1.0%", "1.5%", "2.0%"]
        )
        self._shake_mode.setCurrentText("0.5%")
        trans_layout.addWidget(self._shake_mode, 4, 3)
        self._shake_help = QLabel("Higher % = more shake/jitter effect.")
        self._shake_help.setObjectName("subheading")
        trans_layout.addWidget(self._shake_help, 5, 2, 1, 2)

        layout.addWidget(trans_group)

        color_group = QGroupBox("Color & Quality")
        color_layout = QGridLayout(color_group)
        color_layout.setSpacing(14)

        # Preset Filter / LUT UI
        self._preset_filter_check = QCheckBox("Enable Preset Filter / LUT")
        color_layout.addWidget(self._preset_filter_check, 0, 0, 1, 4)

        color_layout.addWidget(QLabel("Main Category:"), 1, 0)
        self._preset_filter_category = QComboBox()
        from ..effects.preset_filter import PRESET_FILTERS

        self._preset_filter_category.addItems(list(PRESET_FILTERS.keys()))
        color_layout.addWidget(self._preset_filter_category, 1, 1)

        color_layout.addWidget(QLabel("Sub-Filter / Style:"), 1, 2)
        self._preset_filter_style = QComboBox()
        color_layout.addWidget(self._preset_filter_style, 1, 3)

        color_layout.addWidget(QLabel("Description:"), 2, 0)
        self._preset_filter_desc = QLabel()
        self._preset_filter_desc.setObjectName("subheading")
        self._preset_filter_desc.setWordWrap(True)
        color_layout.addWidget(self._preset_filter_desc, 2, 1, 1, 3)

        self._preset_filter_category.currentTextChanged.connect(
            self._on_preset_category_changed
        )
        self._preset_filter_style.currentTextChanged.connect(
            self._on_preset_style_changed
        )

        # Trigger initial dropdown setup
        self._on_preset_category_changed(self._preset_filter_category.currentText())

        self._noise_check = QCheckBox("Noise / Grain")
        color_layout.addWidget(self._noise_check, 3, 0)
        self._noise_mode = QComboBox()
        self._noise_mode.addItems(["film_grain", "light", "random"])
        color_layout.addWidget(self._noise_mode, 3, 1, 1, 3)

        self._motion_blur_check = QCheckBox("Motion Blur")
        color_layout.addWidget(self._motion_blur_check, 4, 0)
        self._motion_blur_frames = QSpinBox()
        self._motion_blur_frames.setRange(2, 8)
        self._motion_blur_frames.setValue(2)
        color_layout.addWidget(self._motion_blur_frames, 4, 1)

        layout.addWidget(color_group)
        layout.addStretch()
        tab.setWidget(container)
        return tab

    MUSIC_SOURCES = [
        ("Meta Sound Collection (Facebook/Instagram)", "https://www.facebook.com/sound/collection/"),
        ("YouTube Audio Library", "https://www.youtube.com/audiolibrary"),
        ("Pixabay Music", "https://pixabay.com/music/"),
    ]

    def _build_music_tab(self) -> QWidget:
        from ..audio.music_library import MUSIC_EXTENSIONS

        tab = QWidget()
        tab_layout = QVBoxLayout(tab)
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(14)

        group = QGroupBox("Background Music (auto-cut to each video's length)")
        grid = QGridLayout(group)
        grid.setSpacing(12)
        grid.setColumnMinimumWidth(0, 205)
        grid.setColumnMinimumWidth(2, 145)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)

        self._music_enable = QCheckBox("Add background music to every video")
        grid.addWidget(self._music_enable, 0, 0, 1, 4)

        grid.addWidget(QLabel("Music folder:"), 1, 0)
        self._music_folder_edit = QLineEdit()
        self._music_folder_edit.setPlaceholderText(
            "Folder with your mp3 / wav / m4a files"
        )
        self._music_folder_edit.editingFinished.connect(self._refresh_music_list)
        grid.addWidget(self._music_folder_edit, 1, 1, 1, 2)
        browse_button = QPushButton("Browse...")
        browse_button.clicked.connect(self._browse_music_folder)
        browse_button.setFixedHeight(36)
        browse_button.setMaximumWidth(150)
        grid.addWidget(
            browse_button,
            1,
            3,
            alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        )

        self._music_count_label = QLabel("No music loaded")
        grid.addWidget(self._music_count_label, 2, 0, 1, 3)
        add_button = QPushButton("Add files...")
        add_button.clicked.connect(self._add_music_files)
        add_button.setFixedHeight(36)
        add_button.setMaximumWidth(150)
        grid.addWidget(
            add_button,
            2,
            3,
            alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        )

        self._music_list = QListWidget()
        self._music_list.setFixedHeight(100)
        grid.addWidget(self._music_list, 3, 0, 1, 4)

        grid.addWidget(QLabel("Pick track:"), 4, 0)
        self._music_selection = QComboBox()
        self._music_selection.addItem("Shuffle (no repeats until all used)", "shuffle")
        self._music_selection.addItem("Random", "random")
        self._music_selection.addItem("In order (A-Z)", "sequential")
        grid.addWidget(self._music_selection, 4, 1)

        grid.addWidget(QLabel("Original audio:"), 4, 2)
        self._music_mode = QComboBox()
        self._music_mode.addItem("Replace (silent AI reels)", "replace")
        self._music_mode.addItem("Mix with original sound", "mix")
        self._music_mode.setCurrentIndex(1)
        grid.addWidget(self._music_mode, 4, 3)

        grid.addWidget(QLabel("Background music volume:"), 5, 0)
        self._music_volume = QSlider(Qt.Orientation.Horizontal)
        self._music_volume.setRange(0, 100)
        self._music_volume.setValue(50)
        self._music_volume_label = QLabel("50%")
        self._music_volume.valueChanged.connect(
            lambda value: self._music_volume_label.setText(f"{value}%")
        )
        grid.addWidget(self._music_volume, 5, 1, 1, 2)
        grid.addWidget(self._music_volume_label, 5, 3)

        grid.addWidget(QLabel("Original video audio volume:"), 6, 0)
        self._music_original_volume = QSlider(Qt.Orientation.Horizontal)
        self._music_original_volume.setRange(0, 100)
        self._music_original_volume.setValue(50)
        self._music_original_volume_label = QLabel("50%")
        self._music_original_volume.valueChanged.connect(
            lambda value: self._music_original_volume_label.setText(f"{value}%")
        )
        grid.addWidget(self._music_original_volume, 6, 1, 1, 2)
        grid.addWidget(self._music_original_volume_label, 6, 3)

        grid.addWidget(QLabel("Fade in (sec):"), 7, 0)
        self._music_fade_in = QDoubleSpinBox()
        self._music_fade_in.setRange(0.0, 5.0)
        self._music_fade_in.setSingleStep(0.25)
        self._music_fade_in.setValue(0.5)
        grid.addWidget(self._music_fade_in, 7, 1)

        grid.addWidget(QLabel("Fade out (sec):"), 7, 2)
        self._music_fade_out = QDoubleSpinBox()
        self._music_fade_out.setRange(0.0, 5.0)
        self._music_fade_out.setSingleStep(0.25)
        self._music_fade_out.setValue(1.5)
        grid.addWidget(self._music_fade_out, 7, 3)

        self._music_random_start = QCheckBox(
            "Start from a random point in longer songs"
        )
        grid.addWidget(self._music_random_start, 8, 0, 1, 4)
        layout.addWidget(group)

        info = QFrame()
        info.setObjectName("card")
        info_layout = QVBoxLayout(info)
        title = QLabel("How the auto-cut works")
        title.setObjectName("subheading")
        info_layout.addWidget(title)
        description = QLabel(
            "- Longer songs are cut to the video length with a fade-out.\n"
            "- Shorter songs are looped until the video ends.\n"
            "- Supported: "
            + ", ".join(sorted(extension.lstrip(".") for extension in MUSIC_EXTENSIONS))
        )
        description.setWordWrap(True)
        info_layout.addWidget(description)
        layout.addWidget(info)

        sources_group = QGroupBox(
            "Free copyright-safe music sources (download, then add the folder above)"
        )
        sources_layout = QHBoxLayout(sources_group)
        for label, url in self.MUSIC_SOURCES:
            button = QPushButton(label)
            button.clicked.connect(lambda _=False, source_url=url: self._open_url(source_url))
            sources_layout.addWidget(button)
        layout.addWidget(sources_group)

        note = QLabel(
            "Always check each track's license. Popular commercial songs can still "
            "get copyright claims even after trimming."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        self._music_extra_files: List[str] = []
        layout.addStretch()
        scroll_area.setWidget(content)
        tab_layout.addWidget(scroll_area)
        return tab

    def _open_url(self, url: str) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl(url))

    def _browse_music_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select music folder")
        if folder:
            self._music_folder_edit.setText(folder)
            self._refresh_music_list()

    def _add_music_files(self) -> None:
        from ..audio.music_library import MUSIC_EXTENSIONS

        pattern = " ".join(f"*{extension}" for extension in sorted(MUSIC_EXTENSIONS))
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select music files", "", f"Audio ({pattern})"
        )
        for path in files:
            if path not in self._music_extra_files:
                self._music_extra_files.append(path)
        if files:
            self._refresh_music_list()

    def _current_music_tracks(self) -> List[str]:
        from ..audio.music_library import scan_music_folder

        tracks = scan_music_folder(self._music_folder_edit.text().strip())
        for path in self._music_extra_files:
            if os.path.isfile(path) and path not in tracks:
                tracks.append(path)
        return tracks

    def _refresh_music_list(self) -> None:
        tracks = self._current_music_tracks()
        self._music_list.clear()
        for path in tracks:
            self._music_list.addItem(os.path.basename(path))
        self._music_count_label.setText(
            f"{len(tracks)} track(s) loaded" if tracks else "No music loaded"
        )

    def _build_export_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(18)

        group = QGroupBox("Video Export Settings")
        grid = QGridLayout(group)
        grid.setSpacing(14)

        grid.addWidget(QLabel("Format:"), 0, 0)
        self._export_format = QComboBox()
        self._export_format.addItems(
            self._config.get("export.formats", ["mp4", "mov", "mkv", "webm"])
        )
        grid.addWidget(self._export_format, 0, 1)

        grid.addWidget(QLabel("Resolution:"), 0, 2)
        self._export_resolution = QComboBox()
        self._export_resolution.addItems(
            self._config.get(
                "export.resolutions", ["original", "720p", "1080p", "2K", "4K"]
            )
        )
        grid.addWidget(self._export_resolution, 0, 3)

        grid.addWidget(QLabel("Encoder:"), 1, 0)
        self._export_encoder = QComboBox()
        self._export_encoder.addItem("Auto (GPU if available)", "auto")
        for enc in self._config.get("export.cpu_encoders", []):
            self._export_encoder.addItem(enc, enc)
        grid.addWidget(self._export_encoder, 1, 1)

        grid.addWidget(QLabel("Bitrate:"), 1, 2)
        self._export_bitrate = QComboBox()
        self._export_bitrate.addItems(["2M", "3M", "5M", "8M", "12M", "20M"])
        self._export_bitrate.setCurrentText("5M")
        grid.addWidget(self._export_bitrate, 1, 3)

        grid.addWidget(QLabel("FPS:"), 2, 0)
        self._export_fps = QSpinBox()
        self._export_fps.setRange(15, 120)
        self._export_fps.setValue(30)
        grid.addWidget(self._export_fps, 2, 1)

        grid.addWidget(QLabel("CRF (quality):"), 2, 2)
        self._export_crf = QSpinBox()
        self._export_crf.setRange(0, 51)
        self._export_crf.setValue(23)
        self._export_crf.setToolTip(
            "Lower = better quality, larger file. 23 is default."
        )
        grid.addWidget(self._export_crf, 2, 3)

        layout.addWidget(group)

        name_group = QGroupBox("Output File Naming")
        name_layout = QGridLayout(name_group)
        name_layout.addWidget(QLabel("Prefix:"), 0, 0)
        self._prefix_edit = QLineEdit()
        self._prefix_edit.setPlaceholderText("e.g., remixed_")
        name_layout.addWidget(self._prefix_edit, 0, 1)
        name_layout.addWidget(QLabel("Suffix:"), 0, 2)
        self._suffix_edit = QLineEdit()
        self._suffix_edit.setPlaceholderText("e.g., _final")
        name_layout.addWidget(self._suffix_edit, 0, 3)
        layout.addWidget(name_group)

        info_card = QFrame()
        info_card.setObjectName("card")
        info_layout = QVBoxLayout(info_card)
        info_title = QLabel("Export Tips")
        info_title.setObjectName("subheading")
        info_layout.addWidget(info_title)
        tips = QLabel(
            "- Use GPU encoder for 5-10x faster processing\n- Original resolution preserves source quality\n- CRF 18-23 is ideal for social media uploads\n- Higher bitrate = better quality but larger files"
        )
        tips.setWordWrap(True)
        info_layout.addWidget(tips)
        layout.addWidget(info_card)

        layout.addStretch()
        return tab

    def _build_processing_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(18)

        self._hw_info = QGroupBox("System Hardware")
        hw_layout = QVBoxLayout(self._hw_info)
        self._hw_label = QLabel("Detecting hardware...")
        self._hw_label.setWordWrap(True)
        hw_layout.addWidget(self._hw_label)
        layout.addWidget(self._hw_info)

        worker_group = QGroupBox("Parallel Processing")
        worker_layout = QHBoxLayout(worker_group)
        worker_layout.setSpacing(16)

        worker_layout.addWidget(QLabel("Parallel Workers:"))
        self._workers_spin = QSpinBox()
        self._workers_spin.setRange(1, 32)
        self._workers_spin.setValue(self._config.get("processing.max_workers", 4))
        worker_layout.addWidget(self._workers_spin)

        self._gpu_check = QCheckBox("Use GPU Acceleration")
        self._gpu_check.setChecked(True)
        worker_layout.addWidget(self._gpu_check)

        worker_layout.addStretch()
        layout.addWidget(worker_group)

        action_card = QFrame()
        action_card.setObjectName("card")
        action_layout = QVBoxLayout(action_card)
        action_layout.setSpacing(16)

        action_title = QLabel("Start Batch Processing")
        action_title.setObjectName("heading")
        action_layout.addWidget(action_title, alignment=Qt.AlignmentFlag.AlignCenter)

        action_desc = QLabel(
            "All configured effects will be applied with randomization per video."
        )
        action_desc.setObjectName("subheading")
        action_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        action_layout.addWidget(action_desc)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(16)
        btn_layout.addStretch()

        self._btn_start = QPushButton("Start Processing")
        self._btn_start.setObjectName("success")
        self._btn_start.setMinimumHeight(52)
        self._btn_start.setMinimumWidth(180)
        self._btn_start.clicked.connect(self._start_processing)
        btn_layout.addWidget(self._btn_start)

        self._btn_pause = QPushButton("Pause")
        self._btn_pause.setObjectName("primary")
        self._btn_pause.setMinimumHeight(52)
        self._btn_pause.setMinimumWidth(140)
        self._btn_pause.setEnabled(False)
        self._btn_pause.clicked.connect(self._pause_processing)
        btn_layout.addWidget(self._btn_pause)

        self._btn_cancel = QPushButton("Cancel")
        self._btn_cancel.setObjectName("danger")
        self._btn_cancel.setMinimumHeight(52)
        self._btn_cancel.setMinimumWidth(140)
        self._btn_cancel.setEnabled(False)
        self._btn_cancel.clicked.connect(self._cancel_processing)
        btn_layout.addWidget(self._btn_cancel)

        btn_layout.addStretch()
        action_layout.addLayout(btn_layout)
        layout.addWidget(action_card)

        layout.addStretch()
        return tab

    def _build_monitor_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(16)

        prog_group = QGroupBox("Overall Progress")
        prog_layout = QVBoxLayout(prog_group)

        self._overall_progress = QProgressBar()
        self._overall_progress.setRange(0, 100)
        self._overall_progress.setValue(0)
        self._overall_progress.setTextVisible(True)
        self._overall_progress.setFormat("%p%  |  %v of %m files")
        self._overall_progress.setMinimumHeight(28)
        prog_layout.addWidget(self._overall_progress)

        stats = QHBoxLayout()
        stats.setSpacing(20)
        self._stat_total = QLabel("Total: 0")
        self._stat_completed = QLabel("Completed: 0")
        self._stat_completed.setObjectName("status_ok")
        self._stat_failed = QLabel("Failed: 0")
        self._stat_failed.setObjectName("status_error")
        self._stat_speed = QLabel("Speed: 0 vid/min")
        self._stat_eta = QLabel("ETA: --")
        for w in [
            self._stat_total,
            self._stat_completed,
            self._stat_failed,
            self._stat_speed,
            self._stat_eta,
        ]:
            stats.addWidget(w)
        stats.addStretch()
        prog_layout.addLayout(stats)
        layout.addWidget(prog_group)

        # Parallel Processing Status
        self._active_group = QGroupBox("Parallel Processing Status")
        group_layout = QVBoxLayout(self._active_group)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        scroll_content = QWidget()
        scroll_content.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.MinimumExpanding
        )
        self._active_layout = QVBoxLayout(scroll_content)
        self._active_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinAndMaxSize)
        self._active_layout.setSpacing(10)
        self._active_layout.setContentsMargins(0, 0, 0, 0)

        self._no_active_label = QLabel("No active tasks.")
        self._no_active_label.setObjectName("subheading")
        self._no_active_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._active_layout.addWidget(self._no_active_label)

        scroll.setWidget(scroll_content)
        group_layout.addWidget(scroll)
        layout.addWidget(self._active_group)

        return tab

    def _apply_theme(self) -> None:
        self.setStyleSheet(self._theme.get_stylesheet())
        self._theme_btn.setText("Dark" if self._theme.mode == "dark" else "Light")

    def _toggle_theme(self) -> None:
        new_mode = "light" if self._theme.mode == "dark" else "dark"
        self._theme.set_mode(new_mode)
        self._settings.set("theme", new_mode)
        self._apply_theme()
        self._event_bus.emit(EventBus.UI_THEME_CHANGED, new_mode)
        self._log(f"Theme switched to {new_mode} mode")

    def _on_preset_category_changed(self, category: str) -> None:
        self._preset_filter_style.blockSignals(True)
        self._preset_filter_style.clear()
        from ..effects.preset_filter import PRESET_FILTERS

        if category in PRESET_FILTERS:
            self._preset_filter_style.addItems(list(PRESET_FILTERS[category].keys()))
        self._preset_filter_style.blockSignals(False)
        self._on_preset_style_changed(self._preset_filter_style.currentText())

    def _on_preset_style_changed(self, style: str) -> None:
        category = self._preset_filter_category.currentText()
        desc = ""
        from ..effects.preset_filter import PRESET_FILTERS

        if category in PRESET_FILTERS and style in PRESET_FILTERS[category]:
            desc = PRESET_FILTERS[category][style].get("description", "")
        self._preset_filter_desc.setText(desc)

    def _build_watermark_tab(self) -> QWidget:
        tab = QWidget()
        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        tab_layout.setSpacing(0)

        scroll_area = QScrollArea(tab)
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        tab_layout.addWidget(scroll_area)

        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setSpacing(18)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_area.setWidget(scroll_content)

        watermark_group = QGroupBox("Watermark Settings")
        watermark_layout = QVBoxLayout(watermark_group)
        watermark_layout.setSpacing(12)

        self._watermark_check = QCheckBox("Enable Watermark Editing")
        self._watermark_check.setToolTip(
            "Turn watermark editing on or off for this project."
        )
        self._watermark_check.setStyleSheet(
            "QToolTip { padding: 4px 6px; font-size: 10pt; }"
        )
        watermark_layout.addWidget(self._watermark_check)

        self._watermark_mode_help = QLabel(
            "Use Add Watermark Only when your video has no existing watermark. Use Remove Existing Watermark + Add New when you want to erase a current logo/text first."
        )
        self._watermark_mode_help.setWordWrap(True)
        self._watermark_mode_help.setObjectName("subheading")
        watermark_layout.addWidget(self._watermark_mode_help)

        mode_selector = QGroupBox("Mode")
        mode_selector.setStyleSheet("QGroupBox { padding-top: 10px; }")
        mode_layout = QHBoxLayout(mode_selector)
        mode_layout.setSpacing(12)
        mode_layout.setContentsMargins(12, 12, 12, 12)
        self._watermark_mode_add_only = QRadioButton("Add Watermark Only")
        self._watermark_mode_remove_replace = QRadioButton(
            "Remove Existing Watermark + Add New"
        )
        self._watermark_mode_group = QButtonGroup(self)
        self._watermark_mode_group.setExclusive(True)
        self._watermark_mode_group.addButton(self._watermark_mode_add_only)
        self._watermark_mode_group.addButton(self._watermark_mode_remove_replace)
        mode_layout.addWidget(self._watermark_mode_add_only)
        mode_layout.addWidget(self._watermark_mode_remove_replace)
        mode_layout.addStretch(1)
        watermark_layout.addWidget(mode_selector)

        self._watermark_box = (0, 0, 0, 0)

        self._watermark_add_panel = QGroupBox("Mode 1: Add Watermark Only")
        self._watermark_add_panel_layout = QFormLayout(self._watermark_add_panel)
        self._watermark_add_panel_layout.setLabelAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        self._watermark_add_panel_layout.setFormAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        self._watermark_add_panel_layout.setRowWrapPolicy(
            QFormLayout.RowWrapPolicy.WrapLongRows
        )
        self._watermark_add_panel_layout.setContentsMargins(16, 12, 16, 12)
        self._watermark_add_panel_layout.setSpacing(12)
        watermark_layout.addWidget(self._watermark_add_panel)

        self._watermark_content_group = QButtonGroup(self)
        self._watermark_content_text = QRadioButton("Text")
        self._watermark_content_logo = QRadioButton("Logo Image")
        self._watermark_content_group.addButton(self._watermark_content_text)
        self._watermark_content_group.addButton(self._watermark_content_logo)
        content_widget = QWidget()
        content_layout = QHBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(10)
        content_layout.addWidget(self._watermark_content_text)
        content_layout.addWidget(self._watermark_content_logo)
        content_layout.addStretch(1)
        self._watermark_add_panel_layout.addRow("Watermark Type:", content_widget)

        self._watermark_text_edit = QLineEdit("AI Bulk Remix")
        self._watermark_add_panel_layout.addRow(
            "Watermark Text:", self._watermark_text_edit
        )

        self._watermark_font_size = QSpinBox()
        self._watermark_font_size.setRange(10, 120)
        self._watermark_font_size.setValue(24)
        self._watermark_add_panel_layout.addRow("Font Size:", self._watermark_font_size)

        self._watermark_color_btn = QPushButton("Select Color...")
        self._watermark_color_btn.clicked.connect(self._select_watermark_color)
        self._watermark_color = QColor("#FFFFFF")
        self._watermark_color_btn.setStyleSheet(
            f"background-color: {self._watermark_color.name()}; color: {'black' if self._watermark_color.lightness() > 128 else 'white'};"
        )
        self._watermark_color_btn.setText(self._watermark_color.name())
        self._watermark_add_panel_layout.addRow(
            "Text Color:", self._watermark_color_btn
        )

        self._watermark_font_style = QComboBox()
        self._watermark_font_style.addItems(["Normal", "Bold", "Italic", "Bold Italic"])
        self._watermark_add_panel_layout.addRow(
            "Font Style:", self._watermark_font_style
        )

        self._watermark_font_family = QComboBox()
        self._watermark_font_family.addItems(
            ["Arial", "Times New Roman", "Impact", "Roboto", "Verdana", "Georgia"]
        )
        self._watermark_add_panel_layout.addRow(
            "Font Family:", self._watermark_font_family
        )

        self._watermark_text_opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._watermark_text_opacity_slider.setRange(0, 100)
        self._watermark_text_opacity_slider.setValue(100)
        self._watermark_text_opacity_slider.setSingleStep(1)
        self._watermark_text_opacity_slider.setPageStep(10)
        self._watermark_text_opacity_value = QLabel("100%")
        self._watermark_text_opacity_slider.valueChanged.connect(
            lambda value: self._watermark_text_opacity_value.setText(f"{value}%")
        )
        text_opacity_widget = QWidget()
        text_opacity_layout = QHBoxLayout(text_opacity_widget)
        text_opacity_layout.setContentsMargins(0, 0, 0, 0)
        text_opacity_layout.setSpacing(8)
        text_opacity_layout.addWidget(self._watermark_text_opacity_slider)
        text_opacity_layout.addWidget(self._watermark_text_opacity_value)
        self._watermark_add_panel_layout.addRow("Text Opacity:", text_opacity_widget)

        self._watermark_background_enable = QCheckBox("Enable Background Behind Text")
        self._watermark_background_controls = QWidget()
        self._watermark_background_controls_layout = QFormLayout(
            self._watermark_background_controls
        )
        self._watermark_background_controls_layout.setContentsMargins(0, 0, 0, 0)
        self._watermark_background_controls_layout.setSpacing(8)
        self._watermark_background_color_btn = QPushButton("Select Color...")
        self._watermark_background_color_btn.clicked.connect(
            self._select_watermark_color
        )
        self._watermark_background_color = QColor("#000000")
        self._watermark_background_color_btn.setStyleSheet(
            f"background-color: {self._watermark_background_color.name()}; color: {'black' if self._watermark_background_color.lightness() > 128 else 'white'};"
        )
        self._watermark_background_color_btn.setText(
            self._watermark_background_color.name()
        )
        self._watermark_background_controls_layout.addRow(
            "Background Color:", self._watermark_background_color_btn
        )
        self._watermark_background_style = QComboBox()
        self._watermark_background_style.addItems(
            ["No Background", "Solid Box", "Rounded Box", "Semi-transparent Box"]
        )
        self._watermark_background_controls_layout.addRow(
            "Background Style:", self._watermark_background_style
        )
        self._watermark_background_opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._watermark_background_opacity_slider.setRange(0, 100)
        self._watermark_background_opacity_slider.setValue(60)
        self._watermark_background_opacity_slider.setSingleStep(1)
        self._watermark_background_opacity_slider.setPageStep(10)
        self._watermark_background_opacity_value = QLabel("60%")
        self._watermark_background_opacity_slider.valueChanged.connect(
            lambda value: self._watermark_background_opacity_value.setText(f"{value}%")
        )
        background_opacity_widget = QWidget()
        background_opacity_layout = QHBoxLayout(background_opacity_widget)
        background_opacity_layout.setContentsMargins(0, 0, 0, 0)
        background_opacity_layout.setSpacing(8)
        background_opacity_layout.addWidget(self._watermark_background_opacity_slider)
        background_opacity_layout.addWidget(self._watermark_background_opacity_value)
        self._watermark_background_controls_layout.addRow(
            "Background Opacity:", background_opacity_widget
        )
        self._watermark_background_controls.setEnabled(False)
        background_container = QWidget()
        background_container_layout = QVBoxLayout(background_container)
        background_container_layout.setContentsMargins(0, 0, 0, 0)
        background_container_layout.setSpacing(8)
        background_container_layout.addWidget(self._watermark_background_enable)
        background_container_layout.addWidget(self._watermark_background_controls)
        self._watermark_add_panel_layout.addRow(
            "Text Background:", background_container
        )

        self._watermark_logo_path = QLineEdit()
        self._watermark_logo_path.setPlaceholderText("Select logo image file...")
        self._watermark_logo_browse = QPushButton("Browse...")
        self._watermark_logo_browse.clicked.connect(self._browse_watermark_logo)
        logo_path_widget = QWidget()
        logo_path_layout = QHBoxLayout(logo_path_widget)
        logo_path_layout.setContentsMargins(0, 0, 0, 0)
        logo_path_layout.setSpacing(8)
        logo_path_layout.addWidget(self._watermark_logo_path)
        logo_path_layout.addWidget(self._watermark_logo_browse)
        self._watermark_add_panel_layout.addRow("Logo Image Path:", logo_path_widget)

        self._watermark_pos_lbl = QLabel("Position:")
        self._watermark_position = QComboBox()
        self._watermark_position.addItems(
            [
                "top_left",
                "top_center",
                "top_right",
                "center_left",
                "center",
                "center_right",
                "bottom_left",
                "bottom_center",
                "bottom_right",
            ]
        )
        self._watermark_add_panel_layout.addRow(
            self._watermark_pos_lbl, self._watermark_position
        )

        self._watermark_opacity = QDoubleSpinBox()
        self._watermark_opacity.setRange(0.1, 1.0)
        self._watermark_opacity.setSingleStep(0.1)
        self._watermark_opacity.setValue(0.8)
        self._watermark_add_panel_layout.addRow("Opacity:", self._watermark_opacity)

        self._watermark_remove_panel = QGroupBox(
            "Mode 2: Remove Existing Watermark + Add New"
        )
        self._watermark_remove_layout = QGridLayout(self._watermark_remove_panel)
        self._watermark_remove_layout.setSpacing(10)
        self._watermark_remove_layout.setContentsMargins(16, 12, 16, 12)
        watermark_layout.addWidget(self._watermark_remove_panel)

        self._watermark_remove_layout.addWidget(
            QLabel("Step 1 — Select Area"), 0, 0, 1, 4
        )
        self._watermark_roi_btn = QPushButton(
            "Select Watermark Area on Video (Draw Box)"
        )
        self._watermark_roi_btn.setObjectName("primary")
        self._watermark_roi_btn.clicked.connect(self._select_watermark_roi)
        self._watermark_remove_layout.addWidget(self._watermark_roi_btn, 1, 0)

        self._watermark_clear_roi_btn = QPushButton("Clear Selection")
        self._watermark_clear_roi_btn.clicked.connect(self._clear_watermark_roi)
        self._watermark_remove_layout.addWidget(self._watermark_clear_roi_btn, 1, 1)

        self._watermark_roi_label = QLabel("No area selected yet")
        self._watermark_roi_label.setObjectName("subheading")
        self._watermark_roi_label.setWordWrap(True)
        self._watermark_remove_layout.addWidget(self._watermark_roi_label, 1, 2, 1, 2)

        self._watermark_remove_layout.addWidget(
            QLabel("Step 2 — Removal Method"), 2, 0, 1, 4
        )
        self._watermark_removal_group = QButtonGroup(self)
        self._watermark_removal_remove_only = QRadioButton(
            "Remove Only (no replacement)"
        )
        self._watermark_removal_replace = QRadioButton(
            "Remove + Replace with New Watermark"
        )
        self._watermark_removal_group.addButton(self._watermark_removal_remove_only)
        self._watermark_removal_group.addButton(self._watermark_removal_replace)
        self._watermark_remove_layout.addWidget(
            self._watermark_removal_remove_only, 3, 0, 1, 2
        )
        self._watermark_remove_layout.addWidget(
            self._watermark_removal_replace, 3, 2, 1, 2
        )

        quality_layout = QHBoxLayout()
        quality_layout.addWidget(QLabel("Removal Quality:"))
        self._watermark_quality_combo = QComboBox()
        self._watermark_quality_combo.addItems([
            "Fast (FFmpeg delogo)",
            "High Quality (OpenCV Inpainting)"
        ])
        self._watermark_quality_combo.setToolTip("Fast uses FFmpeg delogo blur; High Quality uses OpenCV frame-by-frame inpainting for smooth blending.")
        quality_layout.addWidget(self._watermark_quality_combo)
        quality_layout.addStretch()
        self._watermark_remove_layout.addLayout(quality_layout, 4, 0, 1, 4)

        self._watermark_quality_hint = QLabel("ℹ Tight bounding boxes produce cleaner removal results.")
        self._watermark_quality_hint.setObjectName("subheading")
        self._watermark_remove_layout.addWidget(self._watermark_quality_hint, 5, 0, 1, 4)

        self._watermark_replace_panel = QGroupBox("Step 3 — Replacement")
        self._watermark_replace_layout = QFormLayout(self._watermark_replace_panel)
        self._watermark_replace_layout.setLabelAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        self._watermark_replace_layout.setFormAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        self._watermark_replace_layout.setRowWrapPolicy(
            QFormLayout.RowWrapPolicy.WrapLongRows
        )
        self._watermark_replace_layout.setContentsMargins(16, 12, 16, 12)
        self._watermark_replace_layout.setSpacing(12)
        self._watermark_remove_layout.addWidget(
            self._watermark_replace_panel, 6, 0, 1, 4
        )

        self._watermark_replace_text = QRadioButton("Text")
        self._watermark_replace_logo = QRadioButton("Logo Image")
        self._watermark_replace_group = QButtonGroup(self)
        self._watermark_replace_group.addButton(self._watermark_replace_text)
        self._watermark_replace_group.addButton(self._watermark_replace_logo)
        replace_content_widget = QWidget()
        replace_content_layout = QHBoxLayout(replace_content_widget)
        replace_content_layout.setContentsMargins(0, 0, 0, 0)
        replace_content_layout.setSpacing(10)
        replace_content_layout.addWidget(self._watermark_replace_text)
        replace_content_layout.addWidget(self._watermark_replace_logo)
        replace_content_layout.addStretch(1)
        self._watermark_replace_layout.addRow("Watermark Type:", replace_content_widget)

        self._watermark_replace_text_edit = QLineEdit("AI Bulk Remix")
        self._watermark_replace_layout.addRow(
            "Watermark Text:", self._watermark_replace_text_edit
        )

        self._watermark_replace_font_size = QSpinBox()
        self._watermark_replace_font_size.setRange(10, 120)
        self._watermark_replace_font_size.setValue(24)
        self._watermark_replace_layout.addRow(
            "Font Size:", self._watermark_replace_font_size
        )

        self._watermark_replace_color_btn = QPushButton("Select Color...")
        self._watermark_replace_color_btn.clicked.connect(self._select_watermark_color)
        self._watermark_replace_color = QColor("#FFFFFF")
        self._watermark_replace_color_btn.setStyleSheet(
            f"background-color: {self._watermark_replace_color.name()}; color: {'black' if self._watermark_replace_color.lightness() > 128 else 'white'};"
        )
        self._watermark_replace_color_btn.setText(self._watermark_replace_color.name())
        self._watermark_replace_layout.addRow(
            "Text Color:", self._watermark_replace_color_btn
        )

        self._watermark_replace_font_style = QComboBox()
        self._watermark_replace_font_style.addItems(
            ["Normal", "Bold", "Italic", "Bold Italic"]
        )
        self._watermark_replace_layout.addRow(
            "Font Style:", self._watermark_replace_font_style
        )

        self._watermark_replace_font_family = QComboBox()
        self._watermark_replace_font_family.addItems(
            ["Arial", "Times New Roman", "Impact", "Roboto", "Verdana", "Georgia"]
        )
        self._watermark_replace_layout.addRow(
            "Font Family:", self._watermark_replace_font_family
        )

        self._watermark_replace_text_opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._watermark_replace_text_opacity_slider.setRange(0, 100)
        self._watermark_replace_text_opacity_slider.setValue(100)
        self._watermark_replace_text_opacity_slider.setSingleStep(1)
        self._watermark_replace_text_opacity_slider.setPageStep(10)
        self._watermark_replace_text_opacity_value = QLabel("100%")
        self._watermark_replace_text_opacity_slider.valueChanged.connect(
            lambda value: self._watermark_replace_text_opacity_value.setText(
                f"{value}%"
            )
        )
        replace_text_opacity_widget = QWidget()
        replace_text_opacity_layout = QHBoxLayout(replace_text_opacity_widget)
        replace_text_opacity_layout.setContentsMargins(0, 0, 0, 0)
        replace_text_opacity_layout.setSpacing(8)
        replace_text_opacity_layout.addWidget(
            self._watermark_replace_text_opacity_slider
        )
        replace_text_opacity_layout.addWidget(
            self._watermark_replace_text_opacity_value
        )
        self._watermark_replace_layout.addRow(
            "Text Opacity:", replace_text_opacity_widget
        )

        self._watermark_replace_background_enable = QCheckBox(
            "Enable Background Behind Text"
        )
        self._watermark_replace_background_controls = QWidget()
        self._watermark_replace_background_controls_layout = QFormLayout(
            self._watermark_replace_background_controls
        )
        self._watermark_replace_background_controls_layout.setContentsMargins(
            0, 0, 0, 0
        )
        self._watermark_replace_background_controls_layout.setSpacing(8)
        self._watermark_replace_background_color_btn = QPushButton("Select Color...")
        self._watermark_replace_background_color_btn.clicked.connect(
            self._select_watermark_color
        )
        self._watermark_replace_background_color = QColor("#000000")
        self._watermark_replace_background_color_btn.setStyleSheet(
            f"background-color: {self._watermark_replace_background_color.name()}; color: {'black' if self._watermark_replace_background_color.lightness() > 128 else 'white'};"
        )
        self._watermark_replace_background_color_btn.setText(
            self._watermark_replace_background_color.name()
        )
        self._watermark_replace_background_controls_layout.addRow(
            "Background Color:", self._watermark_replace_background_color_btn
        )
        self._watermark_replace_background_style = QComboBox()
        self._watermark_replace_background_style.addItems(
            ["No Background", "Solid Box", "Rounded Box", "Semi-transparent Box"]
        )
        self._watermark_replace_background_controls_layout.addRow(
            "Background Style:", self._watermark_replace_background_style
        )
        self._watermark_replace_background_opacity_slider = QSlider(
            Qt.Orientation.Horizontal
        )
        self._watermark_replace_background_opacity_slider.setRange(0, 100)
        self._watermark_replace_background_opacity_slider.setValue(60)
        self._watermark_replace_background_opacity_slider.setSingleStep(1)
        self._watermark_replace_background_opacity_slider.setPageStep(10)
        self._watermark_replace_background_opacity_value = QLabel("60%")
        self._watermark_replace_background_opacity_slider.valueChanged.connect(
            lambda value: self._watermark_replace_background_opacity_value.setText(
                f"{value}%"
            )
        )
        replace_background_opacity_widget = QWidget()
        replace_background_opacity_layout = QHBoxLayout(
            replace_background_opacity_widget
        )
        replace_background_opacity_layout.setContentsMargins(0, 0, 0, 0)
        replace_background_opacity_layout.setSpacing(8)
        replace_background_opacity_layout.addWidget(
            self._watermark_replace_background_opacity_slider
        )
        replace_background_opacity_layout.addWidget(
            self._watermark_replace_background_opacity_value
        )
        self._watermark_replace_background_controls_layout.addRow(
            "Background Opacity:", replace_background_opacity_widget
        )
        self._watermark_replace_background_controls.setEnabled(False)
        replace_background_container = QWidget()
        replace_background_container_layout = QVBoxLayout(replace_background_container)
        replace_background_container_layout.setContentsMargins(0, 0, 0, 0)
        replace_background_container_layout.setSpacing(8)
        replace_background_container_layout.addWidget(
            self._watermark_replace_background_enable
        )
        replace_background_container_layout.addWidget(
            self._watermark_replace_background_controls
        )
        self._watermark_replace_layout.addRow(
            "Text Background:", replace_background_container
        )

        self._watermark_replace_logo_path = QLineEdit()
        self._watermark_replace_logo_path.setPlaceholderText(
            "Select logo image file..."
        )
        self._watermark_replace_logo_browse = QPushButton("Browse...")
        self._watermark_replace_logo_browse.clicked.connect(self._browse_watermark_logo)
        replace_logo_path_widget = QWidget()
        replace_logo_path_layout = QHBoxLayout(replace_logo_path_widget)
        replace_logo_path_layout.setContentsMargins(0, 0, 0, 0)
        replace_logo_path_layout.setSpacing(8)
        replace_logo_path_layout.addWidget(self._watermark_replace_logo_path)
        replace_logo_path_layout.addWidget(self._watermark_replace_logo_browse)
        self._watermark_replace_layout.addRow(
            "Logo Image Path:", replace_logo_path_widget
        )

        self._watermark_replace_pos_lbl = QLabel("Position:")
        self._watermark_replace_position = QComboBox()
        self._watermark_replace_position.addItems(
            [
                "same_as_removed_area",
                "top_left",
                "top_center",
                "top_right",
                "center_left",
                "center",
                "center_right",
                "bottom_left",
                "bottom_center",
                "bottom_right",
            ]
        )
        self._watermark_replace_layout.addRow(
            self._watermark_replace_pos_lbl, self._watermark_replace_position
        )

        self._watermark_replace_opacity = QDoubleSpinBox()
        self._watermark_replace_opacity.setRange(0.1, 1.0)
        self._watermark_replace_opacity.setSingleStep(0.1)
        self._watermark_replace_opacity.setValue(0.8)
        self._watermark_replace_layout.addRow(
            "Opacity:", self._watermark_replace_opacity
        )

        self._watermark_check.toggled.connect(self._on_watermark_toggled)
        self._watermark_background_enable.toggled.connect(
            self._on_watermark_mode_changed
        )
        self._watermark_replace_background_enable.toggled.connect(
            self._on_watermark_mode_changed
        )
        self._watermark_mode_add_only.toggled.connect(self._on_watermark_mode_changed)
        self._watermark_mode_remove_replace.toggled.connect(
            self._on_watermark_mode_changed
        )
        self._watermark_content_text.toggled.connect(self._on_watermark_mode_changed)
        self._watermark_content_logo.toggled.connect(self._on_watermark_mode_changed)
        self._watermark_removal_remove_only.toggled.connect(
            self._on_watermark_mode_changed
        )
        self._watermark_removal_replace.toggled.connect(self._on_watermark_mode_changed)
        self._watermark_replace_text.toggled.connect(self._on_watermark_mode_changed)
        self._watermark_replace_logo.toggled.connect(self._on_watermark_mode_changed)

        self._watermark_mode_add_only.setChecked(True)
        self._watermark_content_text.setChecked(True)
        self._watermark_replace_text.setChecked(True)
        self._watermark_removal_replace.setChecked(True)
        self._on_watermark_toggled(False)

        scroll_layout.addWidget(watermark_group)
        scroll_layout.addStretch()
        return tab

    def _parse_shake_percentage(self, value: str) -> float:
        cleaned = value.replace("%", "").strip()
        try:
            return float(cleaned)
        except ValueError:
            return 0.5

    def _apply_zoom_level_value(self, value: str | float) -> None:
        try:
            numeric_value = float(str(value).replace("x", "").strip())
        except (TypeError, ValueError):
            return
        clamped_value = max(1.0, min(2.0, numeric_value))
        self._zoom_level.blockSignals(True)
        self._zoom_level.setValue(clamped_value)
        self._zoom_level.blockSignals(False)
        self._update_zoom_level_display(clamped_value)

    def _step_zoom_level_up(self) -> None:
        self._apply_zoom_level_value(self._zoom_level.value() + 0.1)

    def _step_zoom_level_down(self) -> None:
        self._apply_zoom_level_value(self._zoom_level.value() - 0.1)

    def _on_zoom_level_changed(self, text: str) -> None:
        try:
            numeric_value = float(text.replace("x", "").strip())
            self._update_zoom_level_display(numeric_value)
        except ValueError:
            pass

    def _update_zoom_level_display(self, value: float) -> None:
        numeric_value = max(1.0, min(2.0, value))
        display_value = round(numeric_value, 2)
        if abs(display_value - round(display_value)) < 1e-9:
            formatted_value = f"{display_value:.1f}"
        else:
            formatted_value = f"{display_value:.2f}".rstrip("0").rstrip(".")
        self._zoom_level_label_value.setText(f"{formatted_value}x")
        if not self._zoom_level.signalsBlocked():
            self._zoom_level.setValue(display_value)

    def _update_zoom_controls_visibility(self, mode: str | None = None) -> None:
        selected_mode = mode or self._zoom_mode.currentText()
        is_range_mode = selected_mode in {"dynamic", "ken_burns"}
        self._zoom_range_from_label.setVisible(is_range_mode)
        self._zoom_range_from.setVisible(is_range_mode)
        self._zoom_range_to_label.setVisible(is_range_mode)
        self._zoom_range_to.setVisible(is_range_mode)
        if hasattr(self, "_zoom_range_container"):
            self._zoom_range_container.setVisible(is_range_mode)

    def _select_watermark_color(self) -> None:
        sender = self.sender()
        current_color = self._watermark_color
        target_button = self._watermark_color_btn
        storage_attr = "_watermark_color"
        if sender is self._watermark_replace_color_btn:
            current_color = self._watermark_replace_color
            target_button = self._watermark_replace_color_btn
            storage_attr = "_watermark_replace_color"
        elif sender is self._watermark_background_color_btn:
            current_color = self._watermark_background_color
            target_button = self._watermark_background_color_btn
            storage_attr = "_watermark_background_color"
        elif sender is self._watermark_replace_background_color_btn:
            current_color = self._watermark_replace_background_color
            target_button = self._watermark_replace_background_color_btn
            storage_attr = "_watermark_replace_background_color"

        color = QColorDialog.getColor(current_color, self, "Select Watermark Color")
        if color.isValid():
            setattr(self, storage_attr, color)
            target_button.setStyleSheet(
                f"background-color: {color.name()}; color: {'black' if color.lightness() > 128 else 'white'};"
            )
            target_button.setText(color.name())

    def _browse_watermark_logo(self) -> None:
        sender = self.sender()
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Logo Image", "", "Images (*.png *.jpg *.jpeg *.bmp *.webp)"
        )
        if path:
            if sender is self._watermark_replace_logo_browse:
                self._watermark_replace_logo_path.setText(path)
            else:
                self._watermark_logo_path.setText(path)

    def _clear_watermark_roi(self) -> None:
        self._watermark_box = (0, 0, 0, 0)
        self._watermark_roi_label.setText("No area selected yet")
        self._on_watermark_mode_changed()

    def _select_watermark_roi(self) -> None:
        if not self._source_files:
            QMessageBox.warning(
                self,
                "No Videos Selected",
                "Please add and scan source videos on the 'Sources' tab first.",
            )
            return

        video_path = self._source_files[0]
        import cv2

        cap = cv2.VideoCapture(video_path)
        ret, frame = cap.read()
        cap.release()

        if not ret or frame is None:
            QMessageBox.critical(
                self, "Error", f"Failed to read a frame from: {video_path}"
            )
            return

        dialog = WatermarkROIDialog(frame, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            sel = dialog.get_selection()
            if sel and sel[2] > 0 and sel[3] > 0:
                x, y, w, h = sel
                self._watermark_box = (x, y, w, h)
                self._watermark_roi_label.setText(
                    f"Area selected: x={x}, y={y}, w={w}, h={h}"
                )
            else:
                self._watermark_box = (0, 0, 0, 0)
                self._watermark_roi_label.setText("No area selected yet")
        else:
            # User cancelled — preserve any previous selection
            pass

        self._on_watermark_mode_changed()

    def _on_watermark_toggled(self, enabled: bool) -> None:
        self._watermark_mode_help.setEnabled(enabled)
        self._watermark_mode_add_only.setEnabled(enabled)
        self._watermark_mode_remove_replace.setEnabled(enabled)
        self._on_watermark_mode_changed()

    def _on_watermark_mode_changed(self) -> None:
        watermark_enabled = self._watermark_check.isChecked()
        is_add_only = self._watermark_mode_add_only.isChecked()
        is_remove_replace = self._watermark_mode_remove_replace.isChecked()
        is_text = self._watermark_content_text.isChecked()
        is_logo = self._watermark_content_logo.isChecked()
        is_replace = self._watermark_removal_replace.isChecked()
        is_replace_panel_visible = (
            watermark_enabled and is_remove_replace and is_replace
        )

        self._watermark_add_panel.setVisible(watermark_enabled and is_add_only)
        self._watermark_remove_panel.setVisible(watermark_enabled and is_remove_replace)
        self._watermark_replace_panel.setVisible(is_replace_panel_visible)

        self._watermark_add_panel.setEnabled(watermark_enabled and is_add_only)
        self._watermark_remove_panel.setEnabled(watermark_enabled and is_remove_replace)
        self._watermark_replace_panel.setEnabled(is_replace_panel_visible)

        self._watermark_content_text.setEnabled(watermark_enabled and is_add_only)
        self._watermark_content_logo.setEnabled(watermark_enabled and is_add_only)
        self._watermark_replace_text.setEnabled(
            watermark_enabled and is_remove_replace and is_replace
        )
        self._watermark_replace_logo.setEnabled(
            watermark_enabled and is_remove_replace and is_replace
        )

        add_text_enabled = watermark_enabled and is_add_only and is_text
        add_logo_enabled = watermark_enabled and is_add_only and is_logo
        replace_text_enabled = (
            watermark_enabled
            and is_remove_replace
            and is_replace
            and self._watermark_replace_text.isChecked()
        )
        replace_logo_enabled = (
            watermark_enabled
            and is_remove_replace
            and is_replace
            and self._watermark_replace_logo.isChecked()
        )

        self._watermark_text_edit.setEnabled(add_text_enabled)
        self._watermark_font_size.setEnabled(add_text_enabled)
        self._watermark_color_btn.setEnabled(add_text_enabled)
        self._watermark_font_style.setEnabled(add_text_enabled)
        self._watermark_font_family.setEnabled(add_text_enabled)
        self._watermark_text_opacity_slider.setEnabled(add_text_enabled)
        self._watermark_text_opacity_value.setEnabled(add_text_enabled)
        self._watermark_background_enable.setEnabled(add_text_enabled)
        self._watermark_background_controls.setEnabled(
            add_text_enabled and self._watermark_background_enable.isChecked()
        )
        self._watermark_logo_path.setEnabled(add_logo_enabled)
        self._watermark_logo_browse.setEnabled(add_logo_enabled)

        self._watermark_replace_text_edit.setEnabled(replace_text_enabled)
        self._watermark_replace_font_size.setEnabled(replace_text_enabled)
        self._watermark_replace_color_btn.setEnabled(replace_text_enabled)
        self._watermark_replace_font_style.setEnabled(replace_text_enabled)
        self._watermark_replace_font_family.setEnabled(replace_text_enabled)
        self._watermark_replace_text_opacity_slider.setEnabled(replace_text_enabled)
        self._watermark_replace_text_opacity_value.setEnabled(replace_text_enabled)
        self._watermark_replace_background_enable.setEnabled(replace_text_enabled)
        self._watermark_replace_background_controls.setEnabled(
            replace_text_enabled
            and self._watermark_replace_background_enable.isChecked()
        )
        self._watermark_replace_logo_path.setEnabled(replace_logo_enabled)
        self._watermark_replace_logo_browse.setEnabled(replace_logo_enabled)

        self._watermark_roi_btn.setEnabled(watermark_enabled and is_remove_replace)
        self._watermark_clear_roi_btn.setEnabled(
            watermark_enabled and is_remove_replace
        )
        self._watermark_roi_label.setEnabled(watermark_enabled and is_remove_replace)
        self._watermark_removal_remove_only.setEnabled(
            watermark_enabled and is_remove_replace
        )
        self._watermark_removal_replace.setEnabled(
            watermark_enabled and is_remove_replace
        )

        self._watermark_position.setEnabled(watermark_enabled and is_add_only)
        self._watermark_pos_lbl.setEnabled(watermark_enabled and is_add_only)
        self._watermark_replace_position.setEnabled(
            watermark_enabled and is_remove_replace and is_replace
        )
        self._watermark_replace_pos_lbl.setEnabled(
            watermark_enabled and is_remove_replace and is_replace
        )
        self._watermark_opacity.setEnabled(watermark_enabled and is_add_only)
        self._watermark_replace_opacity.setEnabled(
            watermark_enabled and is_remove_replace and is_replace
        )

    def _validate_watermark_config(self) -> tuple[bool, Optional[str]]:
        if not self._watermark_check.isChecked():
            return True, None

        if self._watermark_mode_remove_replace.isChecked():
            has_box = getattr(self, "_watermark_box", (0, 0, 0, 0))[2] > 0
            if not has_box:
                return (
                    False,
                    "Watermark editing mode 'Remove Existing Watermark + Add New' requires you to select the watermark area before processing.",
                )

        if self._watermark_mode_add_only.isChecked():
            if self._watermark_content_text.isChecked():
                if not self._watermark_text_edit.text().strip():
                    return (
                        False,
                        "Please enter watermark text for Add Watermark Only mode.",
                    )
            else:
                if not self._watermark_logo_path.text().strip():
                    return (
                        False,
                        "Please select a logo image path for Add Watermark Only mode.",
                    )
        elif self._watermark_removal_replace.isChecked():
            if self._watermark_replace_text.isChecked():
                if not self._watermark_replace_text_edit.text().strip():
                    return (
                        False,
                        "Please enter watermark text for the replacement watermark.",
                    )
            else:
                if not self._watermark_replace_logo_path.text().strip():
                    return (
                        False,
                        "Please select a logo image path for the replacement watermark.",
                    )

        return True, None

    def _connect_events(self) -> None:
        """Connect EventBus events to signal emissions (thread-safe bridge)."""
        self._event_bus.subscribe(
            EventBus.PROCESSING_STARTED, lambda d: self._sig_processing_started.emit(d)
        )
        self._event_bus.subscribe(
            EventBus.PROCESSING_PROGRESS,
            lambda d: self._sig_processing_progress.emit(d),
        )
        self._event_bus.subscribe(
            EventBus.PROCESSING_COMPLETED,
            lambda d: self._sig_processing_completed.emit(d),
        )
        self._event_bus.subscribe(
            EventBus.PROCESSING_PAUSED, lambda: self._sig_processing_paused.emit()
        )
        self._event_bus.subscribe(
            EventBus.PROCESSING_RESUMED, lambda: self._sig_processing_resumed.emit()
        )
        self._event_bus.subscribe(
            EventBus.PROCESSING_CANCELLED, lambda: self._sig_processing_cancelled.emit()
        )
        self._event_bus.subscribe(
            EventBus.VIDEO_STARTED, lambda d: self._sig_video_started.emit(d)
        )
        self._event_bus.subscribe(
            EventBus.VIDEO_COMPLETED, lambda d: self._sig_video_completed.emit(d)
        )
        self._event_bus.subscribe(
            EventBus.VIDEO_FAILED, lambda d: self._sig_video_failed.emit(d)
        )

    def _connect_signals(self) -> None:
        """Connect Qt signals to UI update slots (all run on main thread)."""
        self._sig_processing_started.connect(self._on_processing_started)
        self._sig_processing_progress.connect(self._on_processing_progress)
        self._sig_processing_completed.connect(self._on_processing_completed)
        self._sig_processing_paused.connect(self._on_processing_paused)
        self._sig_processing_resumed.connect(self._on_processing_resumed)
        self._sig_processing_cancelled.connect(self._on_processing_cancelled)
        self._sig_video_started.connect(self._on_video_started)
        self._sig_video_completed.connect(self._on_video_completed)
        self._sig_video_failed.connect(self._on_video_failed)
        self._sig_ffmpeg_checked.connect(self._on_ffmpeg_checked)

    def _start_ui_timer(self) -> None:
        """Start timer to poll progress and update UI from main thread."""
        self._ui_timer = QTimer(self)
        self._ui_timer.timeout.connect(self._poll_progress)
        self._ui_timer.start(200)  # 200ms refresh rate

    def _poll_progress(self) -> None:
        """Poll batch progress and update UI (runs on main thread)."""
        if not self._is_processing:
            return
        try:
            progress = self._batch_processor.get_progress()
            self._overall_progress.setValue(int(progress.percent))
            self._stat_completed.setText(f"Completed: {progress.completed}")
            self._stat_failed.setText(f"Failed: {progress.failed}")
            if progress.speed > 0:
                self._stat_speed.setText(f"Speed: {progress.speed:.1f} vid/min")
            if progress.estimated_remaining_sec > 0:
                mins = int(progress.estimated_remaining_sec // 60)
                secs = int(progress.estimated_remaining_sec % 60)
                self._stat_eta.setText(f"ETA: {mins}m {secs}s")
        except Exception:
            pass

        # Draining logs removed since Activity Log UI was replaced with Parallel Processing Status
        pass

    def _check_ffmpeg(self):
        self._ffmpeg_thread = FFmpegCheckThread()
        self._ffmpeg_thread.result_ready.connect(self._sig_ffmpeg_checked.emit)
        self._ffmpeg_thread.start()

    def _on_ffmpeg_checked(self, available: bool, message: str):
        self._ffmpeg_available = available
        self._ffmpeg_version = message
        if available:
            self._ffmpeg_status_label.setText(f"FFmpeg OK ({message})")
            self._ffmpeg_status_label.setObjectName("status_ok")
            self._log(f"FFmpeg detected: version {message}")
        else:
            self._ffmpeg_status_label.setText(f"FFmpeg missing")
            self._ffmpeg_status_label.setObjectName("status_error")
            self._log(f"WARNING: {message}. Processing will not work.")
        self._apply_theme()

    def _detect_hardware(self) -> None:
        info = self._system_info.get_info()
        lines = [
            f"<b>CPU:</b> {info.get('cpu', 'Unknown')}",
            f"<b>RAM:</b> {info.get('ram_gb', 'Unknown')} GB",
            f"<b>GPU:</b> {info.get('gpu', 'None detected')}",
            f"<b>FFmpeg:</b> {info.get('ffmpeg_version', 'Not found')}",
            f"<b>Python:</b> {info.get('python_version', 'Unknown')}",
            f"<b>OS:</b> {info.get('os', 'Unknown')}",
            f"<b>Recommended Workers:</b> {self._system_info.recommended_workers()}",
        ]
        self._hw_label.setText("<br>".join(lines))
        self._workers_spin.setValue(self._system_info.recommended_workers())

        from ..ffmpeg.command_builder import CommandBuilder

        builder = CommandBuilder()
        encoders = builder.detect_gpu_encoders()
        if encoders:
            self._gpu_check.setChecked(True)
            self._batch_processor.set_gpu_encoders(encoders)
            self._log(f"GPU encoders detected: {', '.join(encoders)}")
        else:
            self._gpu_check.setChecked(False)
            self._log("No GPU encoders detected. Using CPU encoding.")

    def _browse_input_dir(self) -> None:
        """Open a folder picker — scans all videos inside the selected directory."""
        path = QFileDialog.getExistingDirectory(
            self, "Select Input Directory", self._settings.get("last_input_dir", "")
        )
        if path:
            self._input_dir_edit.setText(path)
            self._settings.set("last_input_dir", path)

    def _import_files(self) -> None:
        """Open a file picker — adds individual video files directly (no folder scan needed)."""
        video_exts = "Video Files (*.mp4 *.mov *.mkv *.avi *.webm *.flv *.wmv *.m4v *.ts *.mts *.3gp)"
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Import Video File(s)",
            self._settings.get("last_input_dir", ""),
            video_exts,
        )
        if not paths:
            return

        added = 0
        for path in paths:
            if path in self._source_files:
                continue  # skip duplicates
            self._source_files.append(path)
            info = self._scanner.get_info(path)
            row = self._file_table.rowCount()
            self._file_table.insertRow(row)
            self._file_table.setItem(
                row, 0, QTableWidgetItem(info.get("filename", os.path.basename(path)))
            )
            self._file_table.setItem(
                row, 1, QTableWidgetItem(info.get("duration_str", ""))
            )
            self._file_table.setItem(
                row, 2, QTableWidgetItem(info.get("resolution", ""))
            )
            self._file_table.setItem(row, 3, QTableWidgetItem(info.get("size", "")))
            status_item = QTableWidgetItem("Ready")
            status_item.setData(Qt.ItemDataRole.UserRole, path)
            self._file_table.setItem(row, 4, status_item)
            added += 1

        self._source_stats.setText(f"{len(self._source_files)} video(s) selected")
        self._statusbar.showMessage(
            f"Imported {added} file(s) — total {len(self._source_files)} selected"
        )
        self._log(f"Imported {added} individual video file(s)")

    def _browse_output_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Select Output Directory", self._settings.get("last_output_dir", "")
        )
        if path:
            self._output_dir_edit.setText(path)
            self._settings.set("last_output_dir", path)

    def _scan_videos(self) -> None:
        input_dir = self._input_dir_edit.text().strip()
        if not input_dir or not os.path.isdir(input_dir):
            QMessageBox.warning(
                self, "Invalid Directory", "Please select a valid input directory."
            )
            return

        self._statusbar.showMessage("Scanning for videos...")
        QApplication.processEvents()

        recursive = self._recursive_check.isChecked()
        files = self._scanner.scan(input_dir, recursive)

        self._source_files = files
        self._file_table.setRowCount(0)
        for f in files:
            info = self._scanner.get_info(f)
            row = self._file_table.rowCount()
            self._file_table.insertRow(row)
            self._file_table.setItem(row, 0, QTableWidgetItem(info.get("filename", "")))
            self._file_table.setItem(
                row, 1, QTableWidgetItem(info.get("duration_str", ""))
            )
            self._file_table.setItem(
                row, 2, QTableWidgetItem(info.get("resolution", ""))
            )
            self._file_table.setItem(row, 3, QTableWidgetItem(info.get("size", "")))
            status_item = QTableWidgetItem("Ready")
            status_item.setData(Qt.ItemDataRole.UserRole, f)
            self._file_table.setItem(row, 4, status_item)

        self._source_stats.setText(f"{len(files)} video(s) selected")
        self._statusbar.showMessage(f"Found {len(files)} video(s)")
        self._log(f"Scanned {input_dir}: {len(files)} video(s) found")

    def _remove_selected_files(self) -> None:
        rows = sorted(
            set(item.row() for item in self._file_table.selectedItems()), reverse=True
        )
        for row in rows:
            self._file_table.removeRow(row)
        self._source_files = []
        for row in range(self._file_table.rowCount()):
            item = self._file_table.item(row, 4)
            if item:
                path = item.data(Qt.ItemDataRole.UserRole)
                if path:
                    self._source_files.append(path)
        self._source_stats.setText(f"{len(self._source_files)} video(s) selected")

    def _clear_files(self) -> None:
        self._source_files.clear()
        self._file_table.setRowCount(0)
        self._source_stats.setText("0 videos selected")
        self._statusbar.showMessage("File list cleared")

    def _build_config(self) -> Dict[str, Any]:
        config = self._config.get_all()
        # randomize only when AI Remix is ON — otherwise use exactly what user selected
        ai_on = self._ai_remix_check.isChecked()

        # Speed value mapping from combo text
        speed_map = {"0.8x": 0.8, "0.9x": 0.9, "1.1x": 1.1, "1.2x": 1.2, "random": 1.0}
        speed_val = speed_map.get(self._speed_mode.currentText(), 1.0)
        speed_randomize = ai_on and self._speed_mode.currentText() == "random"

        config["effects"] = {
            "mirror": {
                "enabled": self._mirror_check.isChecked(),
                "mode": self._mirror_mode.currentText(),
                # randomize mode only if AI remix on AND user picked "alternate" (random-like)
                "randomize": ai_on and self._mirror_mode.currentText() == "alternate",
            },
            "flip": {
                "enabled": self._flip_check.isChecked(),
                "mode": self._flip_mode.currentText(),
                "randomize": False,  # flip has no randomize concept, mode is exact
            },
            "rotation": {
                "enabled": self._rotate_check.isChecked(),
                "mode": self._rotate_mode.currentText(),
                # randomize angle only when AI remix is on AND mode is random/large/small
                "randomize": ai_on
                and self._rotate_mode.currentText()
                in ("small", "large", "clockwise", "anticlockwise", "random"),
            },
            "zoom": {
                "enabled": self._zoom_check.isChecked(),
                "mode": self._zoom_mode.currentText(),
                "min_zoom": (
                    self._zoom_range_from.value()
                    if self._zoom_mode.currentText() in {"dynamic", "ken_burns"}
                    else 1.0
                ),
                "max_zoom": (
                    self._zoom_range_to.value()
                    if self._zoom_mode.currentText() in {"dynamic", "ken_burns"}
                    else self._zoom_level.value()
                ),
                "zoom_level": self._zoom_level.value(),
                # randomize zoom amount only if AI on AND mode is dynamic
                "randomize": ai_on and self._zoom_mode.currentText() == "dynamic",
            },
            "crop": {
                "enabled": self._crop_check.isChecked(),
                "mode": self._crop_mode.currentText(),
                "aspect_ratio": self._crop_aspect.currentText(),
                # randomize crop position only if user chose "random" mode
                "randomize": self._crop_mode.currentText() == "random",
            },
            "speed": {
                "enabled": self._speed_check.isChecked(),
                "speed": speed_val,
                "randomize": speed_randomize,
            },
            "preset_filter": {
                "enabled": self._preset_filter_check.isChecked(),
                "category": self._preset_filter_category.currentText(),
                "style": self._preset_filter_style.currentText(),
                "randomize": False,
            },
            "brightness": {
                "enabled": False,
                "value": 0.0,
                "randomize": ai_on,
                "range": [-0.2, 0.2],
            },
            "contrast": {
                "enabled": False,
                "value": 1.0,
                "randomize": ai_on,
                "range": [0.8, 1.5],
            },
            "saturation": {
                "enabled": False,
                "value": 1.0,
                "randomize": ai_on,
                "range": [0.5, 1.8],
            },
            "hue": {
                "enabled": False,
                "value": 0,
                "randomize": ai_on,
                "range": [-30, 30],
            },
            "sharpness": {
                "enabled": False,
                "value": 1.0,
                "randomize": ai_on,
                "range": [0.5, 2.0],
            },
            "noise": {
                "enabled": self._noise_check.isChecked(),
                "mode": self._noise_mode.currentText(),
                "intensity": 0.05,
                "randomize": ai_on,
            },
            "motion_blur": {
                "enabled": self._motion_blur_check.isChecked(),
                "frames": self._motion_blur_frames.value(),
                "randomize": False,  # use exact frames user set
            },
            "camera_shake": {
                "enabled": self._shake_check.isChecked(),
                "intensity": self._parse_shake_percentage(
                    self._shake_mode.currentText()
                ),
                "randomize": False,  # use exact intensity user set
            },
            "stabilization": {"enabled": False},
            "border": {"enabled": False},
            "background": {"enabled": False},
            "watermark": {
                "enabled": self._watermark_check.isChecked(),
                "mode": (
                    "add_only"
                    if self._watermark_mode_add_only.isChecked()
                    else "remove_replace"
                ),
                "removal_method": (
                    "replace"
                    if self._watermark_removal_replace.isChecked()
                    else "remove_only"
                ),
                "removal_quality": (
                    "inpaint"
                    if hasattr(self, "_watermark_quality_combo")
                    and self._watermark_quality_combo.currentIndex() == 1
                    else "fast"
                ),
                "content_type": (
                    "logo"
                    if (
                        self._watermark_mode_add_only.isChecked()
                        and self._watermark_content_logo.isChecked()
                    )
                    or (
                        self._watermark_mode_remove_replace.isChecked()
                        and self._watermark_removal_replace.isChecked()
                        and self._watermark_replace_logo.isChecked()
                    )
                    else "text"
                ),
                "box": list(getattr(self, "_watermark_box", (0, 0, 0, 0))),
                "text": self._watermark_text_edit.text(),
                "font_size": self._watermark_font_size.value(),
                "color": self._watermark_color.name(),
                "font_style": self._watermark_font_style.currentText(),
                "font_family": self._watermark_font_family.currentText(),
                "text_opacity": self._watermark_text_opacity_slider.value() / 100.0,
                "background_enabled": self._watermark_background_enable.isChecked(),
                "background_color": self._watermark_background_color.name(),
                "background_style": self._watermark_background_style.currentText(),
                "background_opacity": self._watermark_background_opacity_slider.value()
                / 100.0,
                "logo_path": self._watermark_logo_path.text().strip(),
                "position": self._watermark_position.currentText(),
                "opacity": self._watermark_opacity.value(),
                "replace_text": self._watermark_replace_text_edit.text(),
                "replace_font_size": self._watermark_replace_font_size.value(),
                "replace_color": self._watermark_replace_color.name(),
                "replace_font_style": self._watermark_replace_font_style.currentText(),
                "replace_font_family": self._watermark_replace_font_family.currentText(),
                "replace_text_opacity": self._watermark_replace_text_opacity_slider.value()
                / 100.0,
                "replace_background_enabled": self._watermark_replace_background_enable.isChecked(),
                "replace_background_color": self._watermark_replace_background_color.name(),
                "replace_background_style": self._watermark_replace_background_style.currentText(),
                "replace_background_opacity": self._watermark_replace_background_opacity_slider.value()
                / 100.0,
                "replace_logo_path": self._watermark_replace_logo_path.text().strip(),
                "replace_position": self._watermark_replace_position.currentText(),
                "replace_opacity": self._watermark_replace_opacity.value(),
            },
        }
        config["ai_remix"] = {
            "enabled": ai_on,
            "randomize": ai_on,
            "duplicate_prevention": self._dup_prevent_check.isChecked(),
            "min_effects_vary": self._min_effects_vary_spin.value(),
        }
        config.setdefault("audio", {})["background_music"] = {
            "enabled": self._music_enable.isChecked(),
            "folder": self._music_folder_edit.text().strip(),
            "files": self._current_music_tracks(),
            "selection": self._music_selection.currentData(),
            "mode": self._music_mode.currentData(),
            "volume": self._music_volume.value() / 100.0,
            "original_volume": self._music_original_volume.value() / 100.0,
            "fade_in": self._music_fade_in.value(),
            "fade_out": self._music_fade_out.value(),
            "random_start": self._music_random_start.isChecked(),
        }
        encoder = self._export_encoder.currentData()
        if encoder == "auto":
            encoder = "libx264"
            if (
                hasattr(self._batch_processor, "_gpu_encoders")
                and self._batch_processor._gpu_encoders
            ):
                encoder = self._batch_processor._gpu_encoders[0]
        config["export"] = {
            "format": self._export_format.currentText(),
            "resolution": self._export_resolution.currentText(),
            "bitrate": self._export_bitrate.currentText(),
            "fps": self._export_fps.value(),
            "encoder": encoder,
        }
        config["processing"] = {
            "parallel_workers": self._workers_spin.value(),
            "gpu_acceleration": self._gpu_check.isChecked(),
            "max_retries": 3,
            "timeout_per_video": 600,
        }
        return config

    def _start_processing(self) -> None:
        if not self._ffmpeg_available:
            QMessageBox.critical(
                self,
                "FFmpeg Not Found",
                "Cannot start processing: FFmpeg is not installed or not in PATH.\n\n"
                "Please install FFmpeg first.",
            )
            return
        if not self._source_files:
            QMessageBox.warning(
                self, "No Sources", "Please scan and add video files first."
            )
            return
        output_dir = self._output_dir_edit.text().strip()
        if not output_dir:
            QMessageBox.warning(self, "No Output", "Please select an output directory.")
            return

        valid, error = self._validate_watermark_config()
        if not valid:
            QMessageBox.warning(
                self,
                "Watermark Settings",
                error or "Please resolve the watermark settings before processing.",
            )
            return

        if self._music_enable.isChecked() and not self._current_music_tracks():
            QMessageBox.warning(
                self,
                "Background Music",
                "Background music is enabled but no music files were found.\n\n"
                "Choose a music folder or add files in the Music tab, or turn music off.",
            )
            return

        # --- Bug 1: Duplicate-Prevention consent check ---
        # Dry-run randomization on a fresh config copy to discover which effects
        # would be force-enabled, BEFORE we mutate anything.
        if (
            self._ai_remix_check.isChecked()
            and self._dup_prevent_check.isChecked()
        ):
            import copy
            from ..utils.randomizer import Randomizer

            _probe_config = self._build_config()
            _randomizer = Randomizer()
            # Use video_index=0 just to get a representative sample
            _randomizer.apply_randomization(_probe_config, 0)
            forced = _randomizer.get_pending_forced_effects()
            if forced:
                names = ", ".join(f.replace("_", " ").title() for f in forced)
                answer = QMessageBox.question(
                    self,
                    "Duplicate Prevention — Auto-Enable Effects",
                    f"Strict Duplicate Prevention is ON with a minimum of "
                    f"{self._min_effects_vary_spin.value()} varied effects per video.\n\n"
                    f"With your current effect selection, the following additional "
                    f"colour effects will be automatically enabled on some videos "
                    f"to meet that minimum:\n\n"
                    f"  ► {names}\n\n"
                    f"These effects use subtle random values within their default "
                    f"ranges and are designed to be barely perceptible.\n"
                    f"Click OK to proceed, or Cancel to adjust your settings.",
                    QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Ok,
                )
                if answer != QMessageBox.StandardButton.Ok:
                    return  # user cancelled — do not start processing
        # ---------------------------------------------------

        self._output_dir = output_dir
        self._is_processing = True
        self._btn_start.setEnabled(False)
        self._btn_pause.setEnabled(True)
        self._btn_cancel.setEnabled(True)
        self._overall_progress.setValue(0)
        self._clear_active_tasks()

        config = self._build_config()
        self._batch_processor.set_workers(self._workers_spin.value())
        prefix = self._prefix_edit.text()
        suffix = self._suffix_edit.text()

        self._log("=" * 50)
        self._log("BATCH PROCESSING STARTED")
        self._log(f"Total files: {len(self._source_files)}")
        self._log(f"Output directory: {output_dir}")
        self._log(f"Workers: {self._workers_spin.value()}")
        self._log(f"Encoder: {config['export']['encoder']}")
        self._log("=" * 50)

        self._batch_processor.start(
            self._source_files, output_dir, config, prefix, suffix
        )
        self._tabs.setCurrentIndex(5)

    def _pause_processing(self) -> None:
        if self._batch_processor.state == BatchProcessor.STATE_RUNNING:
            self._batch_processor.pause()
            self._btn_pause.setText("Resume")
        elif self._batch_processor.state == BatchProcessor.STATE_PAUSED:
            self._batch_processor.resume()
            self._btn_pause.setText("Pause")

    def _cancel_processing(self) -> None:
        self._batch_processor.cancel()
        self._btn_cancel.setEnabled(False)

    # ===== UI UPDATE SLOTS (all run on main thread via Qt signals) =====

    def _on_processing_started(self, data: Dict[str, Any]) -> None:
        total = data.get("total", 0)
        self._overall_progress.setMaximum(total)
        self._stat_total.setText(f"Total: {total}")
        self._statusbar.showMessage(f"Processing {total} files...")

    def _on_processing_progress(self, data: Dict[str, Any]) -> None:
        idx = data.get("index", 0)
        percent = int(data.get("percent", 0))
        if idx in self._active_widgets:
            self._active_widgets[idx]["progress_bar"].setValue(percent)
            self._active_widgets[idx]["percent_label"].setText(f"{percent}%")

    def _on_processing_completed(self, data: Dict[str, Any]) -> None:
        result = data.get("result")
        self._is_processing = False
        self._btn_start.setEnabled(True)
        self._btn_pause.setEnabled(False)
        self._btn_cancel.setEnabled(False)
        self._btn_pause.setText("Pause")
        self._clear_active_tasks()

        if result:
            self._overall_progress.setValue(result.successful)
            self._stat_completed.setText(f"Completed: {result.successful}")
            self._stat_failed.setText(f"Failed: {result.failed}")
            self._log("=" * 50)
            self._log("BATCH PROCESSING COMPLETED")
            self._log(f"Successful: {result.successful}")
            self._log(f"Failed: {result.failed}")
            self._log(f"Skipped: {result.skipped}")
            self._log(f"Total time: {result.total_time_sec:.1f}s")
            if result.failed_videos:
                self._log(
                    f"Failed: {', '.join(os.path.basename(v) for v in result.failed_videos)}"
                )
            self._log("=" * 50)

        self._statusbar.showMessage("Processing completed")
        state = data.get("state", "")
        if state == BatchProcessor.STATE_COMPLETED:
            QMessageBox.information(
                self,
                "Completed",
                (
                    f"Batch processing finished!\n\n"
                    f"Successful: {result.successful if result else 0}\n"
                    f"Failed: {result.failed if result else 0}\n"
                    f"Time: {result.total_time_sec:.1f}s"
                    if result
                    else ""
                ),
            )
        elif state == BatchProcessor.STATE_ERROR:
            QMessageBox.critical(
                self, "Error", "Batch processing failed. Check logs for details."
            )

    def _on_processing_paused(self) -> None:
        self._log("Processing paused")
        self._statusbar.showMessage("Paused")

    def _on_processing_resumed(self) -> None:
        self._log("Processing resumed")
        self._statusbar.showMessage("Running...")

    def _on_processing_cancelled(self) -> None:
        self._log("Processing cancelled by user")
        self._statusbar.showMessage("Cancelled")
        self._clear_active_tasks()

    def _on_video_started(self, data: Dict[str, Any]) -> None:
        idx = data.get("index", 0)
        input_path = data.get("input", "")
        name = os.path.basename(input_path)
        log_idx = idx + 1
        self._log(f"[{log_idx}/{len(self._source_files)}] START -> {name}")

        # UI Thread check / layout updates
        self._no_active_label.hide()

        task_widget = QWidget()
        task_layout = QHBoxLayout(task_widget)
        task_layout.setContentsMargins(0, 4, 0, 4)
        task_layout.setSpacing(10)

        name_label = QLabel(name)
        name_label.setObjectName("subheading")
        name_label.setMinimumWidth(200)
        name_label.setMaximumWidth(300)
        name_label.setWordWrap(False)

        progress_bar = QProgressBar()
        progress_bar.setRange(0, 100)
        progress_bar.setValue(0)
        progress_bar.setTextVisible(False)
        progress_bar.setMinimumHeight(16)
        progress_bar.setMaximumHeight(16)

        percent_label = QLabel("0%")
        percent_label.setObjectName("subheading")
        percent_label.setMinimumWidth(45)
        percent_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

        task_layout.addWidget(name_label)
        task_layout.addWidget(progress_bar, 1)
        task_layout.addWidget(percent_label)

        self._active_widgets[idx] = {
            "widget": task_widget,
            "progress_bar": progress_bar,
            "percent_label": percent_label,
        }
        self._active_layout.addWidget(task_widget)

    def _on_video_completed(self, data: Dict[str, Any]) -> None:
        idx = data.get("index", 0)
        log_idx = idx + 1
        name = os.path.basename(data.get("input", ""))
        time_s = data.get("encoding_time", 0)
        self._log(f"[{log_idx}/{len(self._source_files)}] DONE  {name} ({time_s:.1f}s)")
        self._update_file_status(data.get("input", ""), "Done")
        self._remove_active_task(idx)

    def _on_video_failed(self, data: Dict[str, Any]) -> None:
        idx = data.get("index", 0)
        log_idx = idx + 1
        name = os.path.basename(data.get("input", ""))
        err = data.get("error", "")
        cmd = data.get("command", "")
        self._log(f"[{log_idx}/{len(self._source_files)}] FAIL  {name}")
        if cmd:
            self._log(f"  CMD: {cmd[:300]}...")
        self._log(f"  ERR: {err[:500]}")
        self._update_file_status(data.get("input", ""), "Failed")
        self._remove_active_task(idx)

    def _remove_active_task(self, idx: int) -> None:
        if idx in self._active_widgets:
            task_info = self._active_widgets.pop(idx)
            widget = task_info["widget"]
            self._active_layout.removeWidget(widget)
            widget.deleteLater()
        if not self._active_widgets:
            self._no_active_label.show()

    def _clear_active_tasks(self) -> None:
        for idx, task_info in list(self._active_widgets.items()):
            widget = task_info["widget"]
            self._active_layout.removeWidget(widget)
            widget.deleteLater()
        self._active_widgets.clear()
        self._no_active_label.show()

    def _update_file_status(self, file_path: str, status: str) -> None:
        for row in range(self._file_table.rowCount()):
            item = self._file_table.item(row, 4)
            if item and item.data(Qt.ItemDataRole.UserRole) == file_path:
                self._file_table.setItem(row, 4, QTableWidgetItem(status))
                break

    def _log(self, message: str) -> None:
        """Thread-safe logging: writes to application logger."""
        self._logger.info(message)

    def _new_project(self):
        self._project.create_new()
        self._source_files.clear()
        self._file_table.setRowCount(0)
        self._input_dir_edit.clear()
        self._output_dir_edit.clear()
        self._log("New project created")

    def _open_project(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Project", "", "AI Bulk Remix Project (*.aibrs)"
        )
        if path:
            self._project.load(path)
            data = self._project.project_data
            sources = data.get("sources", {})
            self._input_dir_edit.setText(sources.get("input_dir", ""))
            self._output_dir_edit.setText(sources.get("output_dir", ""))
            self._source_files = sources.get("files", [])
            self._log(f"Project loaded: {path}")

    def _save_project(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Project", "", "AI Bulk Remix Project (*.aibrs)"
        )
        if path:
            if not path.endswith(".aibrs"):
                path += ".aibrs"
            self._project.save(path)
            self._log(f"Project saved: {path}")

    def _show_about(self):
        QMessageBox.about(
            self,
            "About AI Bulk Remix Studio",
            "<h2>AI Bulk Remix Studio v1.0.0</h2>"
            "<p>A professional desktop application for bulk video processing with "
            "automatic randomization to prevent duplicate content detection.</p>"
            "<p><b>Features:</b></p>"
            "<ul>"
            "<li>Bulk parallel video processing</li>"
            "<li>AI-powered duplicate prevention</li>"
            "<li>GPU acceleration (NVIDIA, Intel, AMD)</li>"
            "<li>20+ video effects with per-video randomization</li>"
            "<li>Real-time progress monitoring</li>"
            "</ul>",
        )

    def closeEvent(self, event):
        if self._is_processing:
            reply = QMessageBox.question(
                self,
                "Confirm Exit",
                "Processing is still running. Are you sure you want to exit?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._batch_processor.cancel()
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()
