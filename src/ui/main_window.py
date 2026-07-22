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
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
    QLabel, QPushButton, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox,
    QCheckBox, QGroupBox, QListWidget, QTableWidget, QTableWidgetItem,
    QProgressBar, QTextEdit, QFileDialog, QMessageBox, QHeaderView,
    QSlider, QSplitter, QFrame, QSizePolicy, QScrollArea, QGridLayout,
    QMenuBar, QMenu, QStatusBar, QApplication, QLayout, QRadioButton,
    QButtonGroup, QColorDialog
)
from PySide6.QtCore import Qt, QTimer, QSize, QThread, Signal
from PySide6.QtGui import QAction, QFont, QColor

from ..core.event_bus import get_event_bus, EventBus
from ..core.project_manager import ProjectManager
from ..core.config_manager import ConfigManager
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
                result = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=5)
                version = result.stdout.split("\n")[0].replace("ffmpeg version ", "").split()[0] if result.stdout else "unknown"
                self.result_ready.emit(True, version)
            except Exception:
                self.result_ready.emit(False, "Error checking FFmpeg")
        else:
            missing = []
            if not ffmpeg_path: missing.append("ffmpeg")
            if not ffprobe_path: missing.append("ffprobe")
            self.result_ready.emit(False, f"Missing: {', '.join(missing)}")


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
        self._logger = setup_logger(level="INFO", log_dir=os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "logs"))

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
        self._input_dir_edit.setPlaceholderText("Select folder containing source videos...")
        dir_layout.addWidget(self._input_dir_edit, 0, 1)

        # Folder browse + Import file buttons side-by-side
        browse_btn_row = QHBoxLayout()
        browse_btn_row.setSpacing(6)
        btn_browse_in = QPushButton("Open Folder")
        btn_browse_in.setObjectName("tool")
        btn_browse_in.setToolTip("Select a folder — all video files inside will be scanned")
        btn_browse_in.clicked.connect(self._browse_input_dir)
        browse_btn_row.addWidget(btn_browse_in)

        btn_import_files = QPushButton("Import File(s)")
        btn_import_files.setObjectName("primary")
        btn_import_files.setToolTip("Pick one or more individual video files to add directly")
        btn_import_files.clicked.connect(self._import_files)
        browse_btn_row.addWidget(btn_import_files)
        dir_layout.addLayout(browse_btn_row, 0, 2)

        dir_layout.addWidget(QLabel("Output Directory:"), 1, 0)
        self._output_dir_edit = QLineEdit()
        self._output_dir_edit.setPlaceholderText("Select folder to save processed videos...")
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
        self._file_table.setHorizontalHeaderLabels(["Filename", "Duration", "Resolution", "Size", "Status"])
        self._file_table.horizontalHeader().setStretchLastSection(True)
        self._file_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._file_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self._file_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self._file_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
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
        container.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.MinimumExpanding)
        layout = QVBoxLayout(container)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinAndMaxSize)
        layout.setSpacing(18)

        ai_group = QGroupBox("AI Remix - Duplicate Prevention Engine")
        ai_layout = QVBoxLayout(ai_group)
        ai_layout.setSpacing(10)
        
        ai_desc = QLabel("Automatically randomizes effects per video so each output has a unique fingerprint. This helps avoid duplicate content penalties on social platforms.")
        ai_desc.setWordWrap(True)
        ai_desc.setObjectName("subheading")
        ai_layout.addWidget(ai_desc)
        
        self._ai_remix_check = QCheckBox("Enable AI Remix / Randomization")
        self._ai_remix_check.setChecked(True)
        ai_layout.addWidget(self._ai_remix_check)
        
        self._dup_prevent_check = QCheckBox("Strict Duplicate Prevention (minimum 3 effects vary per video)")
        self._dup_prevent_check.setChecked(True)
        ai_layout.addWidget(self._dup_prevent_check)
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
        self._rotate_mode.addItems(["small", "large", "clockwise", "anticlockwise", "random"])
        trans_layout.addWidget(self._rotate_mode, 1, 1)

        self._zoom_check = QCheckBox("Zoom")
        trans_layout.addWidget(self._zoom_check, 1, 2)
        self._zoom_mode = QComboBox()
        self._zoom_mode.addItems(["zoom_in", "zoom_out", "dynamic", "ken_burns"])
        trans_layout.addWidget(self._zoom_mode, 1, 3)

        self._crop_check = QCheckBox("Crop")
        trans_layout.addWidget(self._crop_check, 2, 0)
        self._crop_mode = QComboBox()
        self._crop_mode.addItems(["center", "random"])
        trans_layout.addWidget(self._crop_mode, 2, 1)
        trans_layout.addWidget(QLabel("Aspect:"), 2, 2)
        self._crop_aspect = QComboBox()
        self._crop_aspect.addItems(["16:9", "4:3", "1:1", "9:16", "3:2"])
        trans_layout.addWidget(self._crop_aspect, 2, 3)

        self._speed_check = QCheckBox("Speed Change")
        trans_layout.addWidget(self._speed_check, 3, 0)
        self._speed_mode = QComboBox()
        self._speed_mode.addItems(["0.8x", "0.9x", "1.1x", "1.2x", "random"])
        trans_layout.addWidget(self._speed_mode, 3, 1)

        self._shake_check = QCheckBox("Camera Shake")
        trans_layout.addWidget(self._shake_check, 3, 2)
        self._shake_mode = QComboBox()
        self._shake_mode.addItems(["small", "medium", "large"])
        trans_layout.addWidget(self._shake_mode, 3, 3)

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

        self._preset_filter_category.currentTextChanged.connect(self._on_preset_category_changed)
        self._preset_filter_style.currentTextChanged.connect(self._on_preset_style_changed)

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

    def _build_export_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(18)

        group = QGroupBox("Video Export Settings")
        grid = QGridLayout(group)
        grid.setSpacing(14)

        grid.addWidget(QLabel("Format:"), 0, 0)
        self._export_format = QComboBox()
        self._export_format.addItems(self._config.get("export.formats", ["mp4", "mov", "mkv", "webm"]))
        grid.addWidget(self._export_format, 0, 1)

        grid.addWidget(QLabel("Resolution:"), 0, 2)
        self._export_resolution = QComboBox()
        self._export_resolution.addItems(self._config.get("export.resolutions", ["original", "720p", "1080p", "2K", "4K"]))
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
        self._export_crf.setToolTip("Lower = better quality, larger file. 23 is default.")
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
        tips = QLabel("- Use GPU encoder for 5-10x faster processing\n- Original resolution preserves source quality\n- CRF 18-23 is ideal for social media uploads\n- Higher bitrate = better quality but larger files")
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
        
        action_desc = QLabel("All configured effects will be applied with randomization per video.")
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
        for w in [self._stat_total, self._stat_completed, self._stat_failed, self._stat_speed, self._stat_eta]:
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
        scroll_content.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.MinimumExpanding)
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
        layout = QVBoxLayout(tab)
        layout.setSpacing(18)

        watermark_group = QGroupBox("Watermark Settings")
        watermark_layout = QGridLayout(watermark_group)
        watermark_layout.setSpacing(14)

        self._watermark_check = QCheckBox("Enable Watermark Removal / Replacement")
        watermark_layout.addWidget(self._watermark_check, 0, 0, 1, 4)

        # ROI Selection Buttons
        self._watermark_roi_btn = QPushButton("Select Watermark Area on Video (Draw Box)")
        self._watermark_roi_btn.setObjectName("primary")
        self._watermark_roi_btn.clicked.connect(self._select_watermark_roi)
        watermark_layout.addWidget(self._watermark_roi_btn, 1, 0)

        self._watermark_clear_roi_btn = QPushButton("Clear Selection")
        self._watermark_clear_roi_btn.clicked.connect(self._clear_watermark_roi)
        watermark_layout.addWidget(self._watermark_clear_roi_btn, 1, 1)

        self._watermark_roi_label = QLabel("No area selected (will place watermark at corner)")
        self._watermark_roi_label.setObjectName("subheading")
        self._watermark_roi_label.setWordWrap(True)
        watermark_layout.addWidget(self._watermark_roi_label, 1, 2, 1, 2)
        self._watermark_box = (0, 0, 0, 0)

        # Radio buttons for type selection (3 modes)
        self._watermark_mode_remove = QRadioButton("Remove / Inpaint Logo Only")
        self._watermark_mode_text = QRadioButton("Add / Replace with New Text")
        self._watermark_mode_logo = QRadioButton("Add / Replace with Logo Image")
        
        self._watermark_mode_group = QButtonGroup(self)
        self._watermark_mode_group.addButton(self._watermark_mode_remove)
        self._watermark_mode_group.addButton(self._watermark_mode_text)
        self._watermark_mode_group.addButton(self._watermark_mode_logo)
        
        watermark_layout.addWidget(self._watermark_mode_remove, 2, 0)
        watermark_layout.addWidget(self._watermark_mode_text, 2, 1)
        watermark_layout.addWidget(self._watermark_mode_logo, 2, 2, 1, 2)

        # Text Watermark options
        watermark_layout.addWidget(QLabel("Watermark Text:"), 3, 0)
        self._watermark_text_edit = QLineEdit("AI Bulk Remix")
        watermark_layout.addWidget(self._watermark_text_edit, 3, 1)

        watermark_layout.addWidget(QLabel("Font Size:"), 3, 2)
        self._watermark_font_size = QSpinBox()
        self._watermark_font_size.setRange(10, 120)
        self._watermark_font_size.setValue(24)
        watermark_layout.addWidget(self._watermark_font_size, 3, 3)

        watermark_layout.addWidget(QLabel("Text Color:"), 4, 0)
        self._watermark_color_btn = QPushButton("Select Color...")
        self._watermark_color_btn.clicked.connect(self._select_watermark_color)
        watermark_layout.addWidget(self._watermark_color_btn, 4, 1)
        self._watermark_color = QColor("#FFFFFF")

        # Logo Watermark options
        watermark_layout.addWidget(QLabel("Logo Image Path:"), 5, 0)
        self._watermark_logo_path = QLineEdit()
        self._watermark_logo_path.setPlaceholderText("Select logo image file...")
        watermark_layout.addWidget(self._watermark_logo_path, 5, 1, 1, 2)
        
        self._watermark_logo_browse = QPushButton("Browse...")
        self._watermark_logo_browse.clicked.connect(self._browse_watermark_logo)
        watermark_layout.addWidget(self._watermark_logo_browse, 5, 3)

        # Shared options (Position & Opacity)
        self._watermark_pos_lbl = QLabel("Position:")
        watermark_layout.addWidget(self._watermark_pos_lbl, 6, 0)
        self._watermark_position = QComboBox()
        self._watermark_position.addItems(["bottom_right", "bottom_left", "top_right", "top_left", "center"])
        watermark_layout.addWidget(self._watermark_position, 6, 1)

        watermark_layout.addWidget(QLabel("Opacity:"), 6, 2)
        self._watermark_opacity = QDoubleSpinBox()
        self._watermark_opacity.setRange(0.1, 1.0)
        self._watermark_opacity.setSingleStep(0.1)
        self._watermark_opacity.setValue(0.8)
        watermark_layout.addWidget(self._watermark_opacity, 6, 3)

        # Connect toggles to enable/disable widgets
        self._watermark_check.toggled.connect(self._on_watermark_toggled)
        self._watermark_mode_remove.toggled.connect(self._on_watermark_mode_changed)
        self._watermark_mode_text.toggled.connect(self._on_watermark_mode_changed)
        self._watermark_mode_logo.toggled.connect(self._on_watermark_mode_changed)

        # Set default state (Text selected by default)
        self._watermark_mode_text.setChecked(True)
        self._on_watermark_toggled(False)

        layout.addWidget(watermark_group)
        layout.addStretch()
        return tab

    def _select_watermark_color(self) -> None:
        color = QColorDialog.getColor(self._watermark_color, self, "Select Watermark Color")
        if color.isValid():
            self._watermark_color = color
            self._watermark_color_btn.setStyleSheet(
                f"background-color: {color.name()}; color: {'black' if color.lightness() > 128 else 'white'};"
            )
            self._watermark_color_btn.setText(color.name())

    def _browse_watermark_logo(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Logo Image", "", "Images (*.png *.jpg *.jpeg *.bmp *.webp)"
        )
        if path:
            self._watermark_logo_path.setText(path)

    def _clear_watermark_roi(self) -> None:
        self._watermark_box = (0, 0, 0, 0)
        self._watermark_roi_label.setText("No area selected (will place watermark at corner)")
        self._on_watermark_mode_changed()

    def _select_watermark_roi(self) -> None:
        if not self._source_files:
            QMessageBox.warning(self, "No Videos Selected", 
                "Please add and scan source videos on the 'Sources' tab first.")
            return

        video_path = self._source_files[0]
        import cv2
        cap = cv2.VideoCapture(video_path)
        ret, frame = cap.read()
        cap.release()

        if not ret:
            QMessageBox.critical(self, "Error", f"Failed to read a frame from: {video_path}")
            return

        window_title = "Draw a box around the watermark & press ENTER. Press ESC to cancel."
        box = cv2.selectROI(window_title, frame, fromCenter=False, showCrosshair=True)
        cv2.destroyAllWindows()

        x, y, w, h = box
        if w > 0 and h > 0:
            self._watermark_box = (x, y, w, h)
            self._watermark_roi_label.setText(f"Area Selected: Box x={x}, y={y}, w={w}, h={h}")
        else:
            self._watermark_box = (0, 0, 0, 0)
            self._watermark_roi_label.setText("No area selected (will place watermark at corner)")
        
        # Trigger updates to change enable state of position dropdown
        self._on_watermark_mode_changed()

    def _on_watermark_toggled(self, enabled: bool) -> None:
        self._watermark_roi_btn.setEnabled(enabled)
        self._watermark_clear_roi_btn.setEnabled(enabled)
        self._watermark_mode_remove.setEnabled(enabled)
        self._watermark_mode_text.setEnabled(enabled)
        self._watermark_mode_logo.setEnabled(enabled)
        self._watermark_opacity.setEnabled(enabled)
        self._on_watermark_mode_changed()

    def _on_watermark_mode_changed(self) -> None:
        watermark_enabled = self._watermark_check.isChecked()
        is_remove = self._watermark_mode_remove.isChecked()
        is_text = self._watermark_mode_text.isChecked()
        is_logo = self._watermark_mode_logo.isChecked()

        # Text options
        self._watermark_text_edit.setEnabled(watermark_enabled and is_text)
        self._watermark_font_size.setEnabled(watermark_enabled and is_text)
        self._watermark_color_btn.setEnabled(watermark_enabled and is_text)

        # Logo options
        self._watermark_logo_path.setEnabled(watermark_enabled and is_logo)
        self._watermark_logo_browse.setEnabled(watermark_enabled and is_logo)

        # Position dropdown is only enabled if NO box is drawn
        has_box = getattr(self, "_watermark_box", (0, 0, 0, 0))[2] > 0
        show_position = watermark_enabled and not has_box and not is_remove
        self._watermark_position.setEnabled(show_position)
        self._watermark_pos_lbl.setEnabled(show_position)

    def _connect_events(self) -> None:
        """Connect EventBus events to signal emissions (thread-safe bridge)."""
        self._event_bus.subscribe(EventBus.PROCESSING_STARTED, lambda d: self._sig_processing_started.emit(d))
        self._event_bus.subscribe(EventBus.PROCESSING_PROGRESS, lambda d: self._sig_processing_progress.emit(d))
        self._event_bus.subscribe(EventBus.PROCESSING_COMPLETED, lambda d: self._sig_processing_completed.emit(d))
        self._event_bus.subscribe(EventBus.PROCESSING_PAUSED, lambda: self._sig_processing_paused.emit())
        self._event_bus.subscribe(EventBus.PROCESSING_RESUMED, lambda: self._sig_processing_resumed.emit())
        self._event_bus.subscribe(EventBus.PROCESSING_CANCELLED, lambda: self._sig_processing_cancelled.emit())
        self._event_bus.subscribe(EventBus.VIDEO_STARTED, lambda d: self._sig_video_started.emit(d))
        self._event_bus.subscribe(EventBus.VIDEO_COMPLETED, lambda d: self._sig_video_completed.emit(d))
        self._event_bus.subscribe(EventBus.VIDEO_FAILED, lambda d: self._sig_video_failed.emit(d))

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
            f"<b>Recommended Workers:</b> {self._system_info.recommended_workers()}"
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
        path = QFileDialog.getExistingDirectory(self, "Select Input Directory", self._settings.get("last_input_dir", ""))
        if path:
            self._input_dir_edit.setText(path)
            self._settings.set("last_input_dir", path)

    def _import_files(self) -> None:
        """Open a file picker — adds individual video files directly (no folder scan needed)."""
        video_exts = "Video Files (*.mp4 *.mov *.mkv *.avi *.webm *.flv *.wmv *.m4v *.ts *.mts *.3gp)"
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Import Video File(s)",
            self._settings.get("last_input_dir", ""),
            video_exts
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
            self._file_table.setItem(row, 0, QTableWidgetItem(info.get("filename", os.path.basename(path))))
            self._file_table.setItem(row, 1, QTableWidgetItem(info.get("duration_str", "")))
            self._file_table.setItem(row, 2, QTableWidgetItem(info.get("resolution", "")))
            self._file_table.setItem(row, 3, QTableWidgetItem(info.get("size", "")))
            status_item = QTableWidgetItem("Ready")
            status_item.setData(Qt.ItemDataRole.UserRole, path)
            self._file_table.setItem(row, 4, status_item)
            added += 1

        self._source_stats.setText(f"{len(self._source_files)} video(s) selected")
        self._statusbar.showMessage(f"Imported {added} file(s) — total {len(self._source_files)} selected")
        self._log(f"Imported {added} individual video file(s)")

    def _browse_output_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select Output Directory", self._settings.get("last_output_dir", ""))
        if path:
            self._output_dir_edit.setText(path)
            self._settings.set("last_output_dir", path)

    def _scan_videos(self) -> None:
        input_dir = self._input_dir_edit.text().strip()
        if not input_dir or not os.path.isdir(input_dir):
            QMessageBox.warning(self, "Invalid Directory", "Please select a valid input directory.")
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
            self._file_table.setItem(row, 1, QTableWidgetItem(info.get("duration_str", "")))
            self._file_table.setItem(row, 2, QTableWidgetItem(info.get("resolution", "")))
            self._file_table.setItem(row, 3, QTableWidgetItem(info.get("size", "")))
            status_item = QTableWidgetItem("Ready")
            status_item.setData(Qt.ItemDataRole.UserRole, f)
            self._file_table.setItem(row, 4, status_item)

        self._source_stats.setText(f"{len(files)} video(s) selected")
        self._statusbar.showMessage(f"Found {len(files)} video(s)")
        self._log(f"Scanned {input_dir}: {len(files)} video(s) found")

    def _remove_selected_files(self) -> None:
        rows = sorted(set(item.row() for item in self._file_table.selectedItems()), reverse=True)
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
                "randomize": ai_on and self._rotate_mode.currentText() in ("small", "large", "clockwise", "anticlockwise", "random"),
            },
            "zoom": {
                "enabled": self._zoom_check.isChecked(),
                "mode": self._zoom_mode.currentText(),
                "min_zoom": 1.0,
                "max_zoom": 1.5,
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
                "intensity": self._shake_mode.currentText(),
                "randomize": False,  # use exact intensity user set
            },
            "stabilization": {"enabled": False},
            "border": {"enabled": False},
            "background": {"enabled": False},
            "watermark": {
                "enabled": self._watermark_check.isChecked(),
                "mode": "remove" if self._watermark_mode_remove.isChecked() else ("replace_text" if self._watermark_mode_text.isChecked() else "replace_logo"),
                "box": list(getattr(self, "_watermark_box", (0, 0, 0, 0))),
                "text": self._watermark_text_edit.text(),
                "font_size": self._watermark_font_size.value(),
                "color": self._watermark_color.name(),
                "logo_path": self._watermark_logo_path.text().strip(),
                "position": self._watermark_position.currentText(),
                "opacity": self._watermark_opacity.value()
            },
        }
        config["ai_remix"] = {
            "enabled": ai_on,
            "randomize": ai_on,
            "duplicate_prevention": self._dup_prevent_check.isChecked(),
            "min_effects_vary": 3,
        }
        encoder = self._export_encoder.currentData()
        if encoder == "auto":
            encoder = "libx264"
            if hasattr(self._batch_processor, '_gpu_encoders') and self._batch_processor._gpu_encoders:
                encoder = self._batch_processor._gpu_encoders[0]
        config["export"] = {
            "format": self._export_format.currentText(),
            "resolution": self._export_resolution.currentText(),
            "bitrate": self._export_bitrate.currentText(),
            "fps": self._export_fps.value(),
            "encoder": encoder
        }
        config["processing"] = {
            "parallel_workers": self._workers_spin.value(),
            "gpu_acceleration": self._gpu_check.isChecked(),
            "max_retries": 3,
            "timeout_per_video": 600
        }
        return config

    def _start_processing(self) -> None:
        if not self._ffmpeg_available:
            QMessageBox.critical(self, "FFmpeg Not Found", 
                "Cannot start processing: FFmpeg is not installed or not in PATH.\n\n"
                "Please install FFmpeg first.")
            return
        if not self._source_files:
            QMessageBox.warning(self, "No Sources", "Please scan and add video files first.")
            return
        output_dir = self._output_dir_edit.text().strip()
        if not output_dir:
            QMessageBox.warning(self, "No Output", "Please select an output directory.")
            return

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

        self._batch_processor.start(self._source_files, output_dir, config, prefix, suffix)
        self._tabs.setCurrentIndex(4)

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
        total = data.get('total', 0)
        self._overall_progress.setMaximum(total)
        self._stat_total.setText(f"Total: {total}")
        self._statusbar.showMessage(f"Processing {total} files...")

    def _on_processing_progress(self, data: Dict[str, Any]) -> None:
        idx = data.get('index', 0)
        percent = int(data.get('percent', 0))
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
                self._log(f"Failed: {', '.join(os.path.basename(v) for v in result.failed_videos)}")
            self._log("=" * 50)

        self._statusbar.showMessage("Processing completed")
        state = data.get("state", "")
        if state == BatchProcessor.STATE_COMPLETED:
            QMessageBox.information(self, "Completed", 
                f"Batch processing finished!\n\n"
                f"Successful: {result.successful if result else 0}\n"
                f"Failed: {result.failed if result else 0}\n"
                f"Time: {result.total_time_sec:.1f}s" if result else "")
        elif state == BatchProcessor.STATE_ERROR:
            QMessageBox.critical(self, "Error", "Batch processing failed. Check logs for details.")

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
        idx = data.get('index', 0)
        input_path = data.get('input', '')
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
        percent_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        
        task_layout.addWidget(name_label)
        task_layout.addWidget(progress_bar, 1)
        task_layout.addWidget(percent_label)
        
        self._active_widgets[idx] = {
            "widget": task_widget,
            "progress_bar": progress_bar,
            "percent_label": percent_label
        }
        self._active_layout.addWidget(task_widget)

    def _on_video_completed(self, data: Dict[str, Any]) -> None:
        idx = data.get('index', 0)
        log_idx = idx + 1
        name = os.path.basename(data.get('input', ''))
        time_s = data.get('encoding_time', 0)
        self._log(f"[{log_idx}/{len(self._source_files)}] DONE  {name} ({time_s:.1f}s)")
        self._update_file_status(data.get("input", ""), "Done")
        self._remove_active_task(idx)

    def _on_video_failed(self, data: Dict[str, Any]) -> None:
        idx = data.get('index', 0)
        log_idx = idx + 1
        name = os.path.basename(data.get('input', ''))
        err = data.get('error', '')
        cmd = data.get('command', '')
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
        path, _ = QFileDialog.getOpenFileName(self, "Open Project", "", "AI Bulk Remix Project (*.aibrs)")
        if path:
            self._project.load(path)
            data = self._project.project_data
            sources = data.get("sources", {})
            self._input_dir_edit.setText(sources.get("input_dir", ""))
            self._output_dir_edit.setText(sources.get("output_dir", ""))
            self._source_files = sources.get("files", [])
            self._log(f"Project loaded: {path}")

    def _save_project(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save Project", "", "AI Bulk Remix Project (*.aibrs)")
        if path:
            if not path.endswith(".aibrs"):
                path += ".aibrs"
            self._project.save(path)
            self._log(f"Project saved: {path}")

    def _show_about(self):
        QMessageBox.about(self, "About AI Bulk Remix Studio",
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
            "</ul>")

    def closeEvent(self, event):
        if self._is_processing:
            reply = QMessageBox.question(self, "Confirm Exit",
                "Processing is still running. Are you sure you want to exit?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                self._batch_processor.cancel()
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()
