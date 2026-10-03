"""
Theme - Professional QSS stylesheets for dark/light modes.
Catppuccin-inspired modern color palette.
"""

from typing import Dict


class Theme:
    """Manages application themes with professional styling."""

    COLORS = {
        "dark": {
            "bg_primary": "#1e1e2e",
            "bg_secondary": "#252536",
            "bg_tertiary": "#2d2d44",
            "bg_card": "#24243a",
            "bg_input": "#181825",
            "text_primary": "#cdd6f4",
            "text_secondary": "#a6adc8",
            "text_muted": "#6c7086",
            "accent": "#89b4fa",
            "accent_hover": "#b4befe",
            "accent_bg": "#313244",
            "success": "#a6e3a1",
            "success_bg": "#2d3b2d",
            "warning": "#f9e2af",
            "warning_bg": "#3b352d",
            "error": "#f38ba8",
            "error_bg": "#3b2d35",
            "info": "#74c7ec",
            "border": "#45475a",
            "border_focus": "#89b4fa",
            "button_bg": "#313244",
            "button_hover": "#45475a",
            "button_pressed": "#585b70",
            "progress_bg": "#313244",
            "progress_chunk": "#89b4fa",
            "log_bg": "#11111b",
            "log_text": "#cdd6f4",
            "tab_bg": "#181825",
            "tab_selected": "#252536",
            "tab_hover": "#1e1e2e",
            "scrollbar": "#585b70",
            "scrollbar_hover": "#89b4fa",
            "tooltip_bg": "#2d2d44",
            "tooltip_text": "#cdd6f4",
            "menu_bg": "#252536",
            "menu_hover": "#89b4fa",
        },
        "light": {
            "bg_primary": "#eff1f5",
            "bg_secondary": "#e6e9ef",
            "bg_tertiary": "#dce0e8",
            "bg_card": "#ffffff",
            "bg_input": "#ffffff",
            "text_primary": "#4c4f69",
            "text_secondary": "#6c6f85",
            "text_muted": "#8c8fa1",
            "accent": "#1e66f5",
            "accent_hover": "#7287fd",
            "accent_bg": "#e6e9ef",
            "success": "#40a02b",
            "success_bg": "#e6f5e1",
            "warning": "#df8e1d",
            "warning_bg": "#f5f0e1",
            "error": "#d20f39",
            "error_bg": "#f5e1e6",
            "info": "#209fb5",
            "border": "#bcc0cc",
            "border_focus": "#1e66f5",
            "button_bg": "#ccd0da",
            "button_hover": "#bcc0cc",
            "button_pressed": "#acb0be",
            "progress_bg": "#ccd0da",
            "progress_chunk": "#1e66f5",
            "log_bg": "#e6e9ef",
            "log_text": "#4c4f69",
            "tab_bg": "#dce0e8",
            "tab_selected": "#eff1f5",
            "tab_hover": "#e6e9ef",
            "scrollbar": "#8c8fa1",
            "scrollbar_hover": "#1e66f5",
            "tooltip_bg": "#dce0e8",
            "tooltip_text": "#4c4f69",
            "menu_bg": "#e6e9ef",
            "menu_hover": "#1e66f5",
        }
    }

    def __init__(self, mode: str = "dark"):
        self._mode = mode
        self._colors = self.COLORS.get(mode, self.COLORS["dark"])

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        self._colors = self.COLORS.get(mode, self.COLORS["dark"])

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def colors(self) -> Dict[str, str]:
        return self._colors.copy()

    def get_stylesheet(self) -> str:
        """Generate complete professional QSS stylesheet."""
        c = self._colors
        return f"""
        /* ===== GLOBAL ===== */
        QMainWindow {{
            background-color: {c['bg_primary']};
        }}
        QWidget {{
            background-color: {c['bg_primary']};
            color: {c['text_primary']};
            font-family: 'Segoe UI', 'SF Pro Display', 'Helvetica Neue', sans-serif;
            font-size: 13px;
            outline: none;
        }}
        QLabel {{
            background-color: transparent;
        }}
        
        /* ===== TABS ===== */
        QTabWidget::pane {{
            border: 1px solid {c['border']};
            background-color: {c['bg_secondary']};
            border-radius: 8px;
            border-top-left-radius: 0px;
            padding: 12px;
        }}
        QTabBar::tab {{
            background-color: {c['tab_bg']};
            color: {c['text_secondary']};
            padding: 10px 22px;
            border-top-left-radius: 8px;
            border-top-right-radius: 8px;
            margin-right: 3px;
            font-weight: 500;
        }}
        QTabBar::tab:selected {{
            background-color: {c['tab_selected']};
            color: {c['text_primary']};
            border-bottom: 3px solid {c['accent']};
        }}
        QTabBar::tab:hover:!selected {{
            background-color: {c['tab_hover']};
            color: {c['text_primary']};
        }}
        
        /* ===== BUTTONS ===== */
        QPushButton {{
            background-color: {c['button_bg']};
            color: {c['text_primary']};
            border: 1px solid {c['border']};
            padding: 8px 18px;
            border-radius: 6px;
            font-weight: 500;
            min-height: 20px;
        }}
        QPushButton:hover {{
            background-color: {c['button_hover']};
            border-color: {c['border_focus']};
        }}
        QPushButton:pressed {{
            background-color: {c['button_pressed']};
        }}
        QPushButton:disabled {{
            background-color: {c['bg_tertiary']};
            color: {c['text_muted']};
            border-color: {c['border']};
        }}
        QPushButton#primary {{
            background-color: {c['accent']};
            color: {c['bg_primary']};
            border: none;
            font-weight: 600;
        }}
        QPushButton#primary:hover {{
            background-color: {c['accent_hover']};
        }}
        QPushButton#primary:disabled {{
            background-color: {c['accent_bg']};
            color: {c['text_muted']};
        }}
        QPushButton#danger {{
            background-color: {c['error']};
            color: white;
            border: none;
            font-weight: 600;
        }}
        QPushButton#danger:hover {{
            background-color: #ff6b8a;
        }}
        QPushButton#success {{
            background-color: {c['success']};
            color: {c['bg_primary']};
            border: none;
            font-weight: 600;
        }}
        QPushButton#tool {{
            background-color: transparent;
            border: 1px solid {c['border']};
            padding: 6px 12px;
        }}
        
        /* ===== INPUTS ===== */
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
            background-color: {c['bg_input']};
            color: {c['text_primary']};
            border: 1px solid {c['border']};
            padding: 7px 10px;
            border-radius: 6px;
            selection-background-color: {c['accent']};
        }}
        QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
            border-color: {c['border_focus']};
        }}
        QComboBox::drop-down {{
            border: none;
            width: 28px;
        }}
        QComboBox::down-arrow {{
            image: none;
            border-left: 5px solid transparent;
            border-right: 5px solid transparent;
            border-top: 6px solid {c['text_secondary']};
            width: 0px;
            height: 0px;
        }}
        QComboBox QAbstractItemView {{
            background-color: {c['bg_input']};
            color: {c['text_primary']};
            selection-background-color: {c['accent']};
            selection-color: {c['bg_primary']};
            border: 1px solid {c['border']};
            border-radius: 6px;
            padding: 4px;
        }}
        QSpinBox::up-button, QDoubleSpinBox::up-button {{
            subcontrol-origin: border;
            subcontrol-position: top right;
            width: 20px;
            border-left: 1px solid {c['border']};
        }}
        QSpinBox::down-button, QDoubleSpinBox::down-button {{
            subcontrol-origin: border;
            subcontrol-position: bottom right;
            width: 20px;
            border-left: 1px solid {c['border']};
        }}
        
        /* ===== SLIDERS ===== */
        QSlider::groove:horizontal {{
            height: 6px;
            background: {c['progress_bg']};
            border-radius: 3px;
        }}
        QSlider::handle:horizontal {{
            background: {c['accent']};
            width: 18px;
            height: 18px;
            margin: -6px 0;
            border-radius: 9px;
            border: 2px solid {c['bg_primary']};
        }}
        QSlider::handle:horizontal:hover {{
            background: {c['accent_hover']};
            width: 20px;
            height: 20px;
            margin: -7px 0;
            border-radius: 10px;
        }}
        QSlider::sub-page:horizontal {{
            background: {c['accent']};
            border-radius: 3px;
        }}
        
        /* ===== PROGRESS ===== */
        QProgressBar {{
            border: 1px solid {c['border']};
            border-radius: 6px;
            text-align: center;
            background-color: {c['progress_bg']};
            color: {c['text_primary']};
            font-weight: 500;
            min-height: 24px;
        }}
        QProgressBar::chunk {{
            background-color: {c['progress_chunk']};
            border-radius: 6px;
        }}
        
        /* ===== GROUP BOX ===== */
        QGroupBox {{
            border: 1px solid {c['border']};
            border-radius: 8px;
            margin-top: 14px;
            padding-top: 14px;
            padding-bottom: 10px;
            padding-left: 12px;
            padding-right: 12px;
            font-weight: 600;
            color: {c['text_secondary']};
            background-color: {c['bg_card']};
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 14px;
            padding: 0 8px;
            color: {c['accent']};
        }}
        
        /* ===== CHECKBOX ===== */
        QCheckBox {{
            spacing: 10px;
            font-weight: 500;
        }}
        QCheckBox::indicator {{
            width: 20px;
            height: 20px;
            border-radius: 5px;
            border: 2px solid {c['border']};
            background-color: {c['bg_input']};
        }}
        QCheckBox::indicator:checked {{
            background-color: {c['accent']};
            border-color: {c['accent']};
            image: url(data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTIiIGhlaWdodD0iMTIiIHZpZXdCb3g9IjAgMCAxMiAxMiIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cGF0aCBkPSJNMiA2TDUgOUwxMCAzIiBzdHJva2U9IiMxZTFlMmUiIHN0cm9rZS13aWR0aD0iMiIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIi8+PC9zdmc+);
        }}
        QCheckBox::indicator:hover {{
            border-color: {c['accent']};
        }}
        
        /* ===== TABLES & LISTS ===== */
        QListWidget, QTableWidget {{
            background-color: {c['bg_input']};
            border: 1px solid {c['border']};
            border-radius: 6px;
            outline: none;
            gridline-color: {c['border']};
            alternate-background-color: {c['bg_secondary']};
        }}
        QListWidget::item:selected, QTableWidget::item:selected {{
            background-color: {c['accent']};
            color: {c['bg_primary']};
        }}
        QListWidget::item:hover:!selected, QTableWidget::item:hover:!selected {{
            background-color: {c['accent_bg']};
        }}
        QHeaderView::section {{
            background-color: {c['bg_tertiary']};
            color: {c['text_secondary']};
            padding: 8px;
            border: none;
            border-bottom: 2px solid {c['border']};
            font-weight: 600;
        }}
        
        /* ===== SCROLLBAR ===== */
        QScrollBar:vertical {{
            background-color: transparent;
            width: 10px;
            border-radius: 5px;
        }}
        QScrollBar::handle:vertical {{
            background-color: {c['scrollbar']};
            border-radius: 5px;
            min-height: 40px;
        }}
        QScrollBar::handle:vertical:hover {{
            background-color: {c['scrollbar_hover']};
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
        }}
        QScrollBar:horizontal {{
            background-color: transparent;
            height: 10px;
            border-radius: 5px;
        }}
        QScrollBar::handle:horizontal {{
            background-color: {c['scrollbar']};
            border-radius: 5px;
            min-width: 40px;
        }}
        QScrollBar::handle:horizontal:hover {{
            background-color: {c['scrollbar_hover']};
        }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
            width: 0px;
        }}
        
        /* ===== TEXT EDIT / LOG ===== */
        QTextEdit {{
            background-color: {c['log_bg']};
            color: {c['log_text']};
            border: 1px solid {c['border']};
            border-radius: 6px;
            font-family: 'JetBrains Mono', 'Consolas', 'Monaco', monospace;
            font-size: 12px;
            padding: 8px;
            selection-background-color: {c['accent']};
        }}
        
        /* ===== LABELS ===== */
        QLabel {{
            color: {c['text_primary']};
        }}
        QLabel#heading {{
            font-size: 22px;
            font-weight: 700;
            color: {c['accent']};
            padding-bottom: 4px;
        }}
        QLabel#subheading {{
            font-size: 14px;
            font-weight: 600;
            color: {c['text_secondary']};
        }}
        QLabel#status_ok {{
            color: {c['success']};
            font-weight: 600;
        }}
        QLabel#status_warn {{
            color: {c['warning']};
            font-weight: 600;
        }}
        QLabel#status_error {{
            color: {c['error']};
            font-weight: 600;
        }}
        
        /* ===== MENUS ===== */
        QMenuBar {{
            background-color: {c['bg_secondary']};
            color: {c['text_primary']};
            border-bottom: 1px solid {c['border']};
        }}
        QMenuBar::item:selected {{
            background-color: {c['accent']};
            color: {c['bg_primary']};
            border-radius: 4px;
        }}
        QMenu {{
            background-color: {c['menu_bg']};
            color: {c['text_primary']};
            border: 1px solid {c['border']};
            border-radius: 6px;
            padding: 6px;
        }}
        QMenu::item {{
            padding: 6px 24px;
            border-radius: 4px;
        }}
        QMenu::item:selected {{
            background-color: {c['menu_hover']};
            color: {c['bg_primary']};
        }}
        QMenu::separator {{
            height: 1px;
            background-color: {c['border']};
            margin: 6px 0px;
        }}
        
        /* ===== TOOLTIP ===== */
        QToolTip {{
            background-color: {c['tooltip_bg']};
            color: {c['tooltip_text']};
            border: 1px solid {c['border']};
            border-radius: 6px;
            padding: 6px 10px;
            font-size: 12px;
        }}
        
        /* ===== SPLITTER ===== */
        QSplitter::handle {{
            background-color: {c['border']};
        }}
        QSplitter::handle:horizontal {{
            width: 2px;
        }}
        QSplitter::handle:vertical {{
            height: 2px;
        }}
        
        /* ===== FRAME ===== */
        QFrame#card {{
            background-color: {c['bg_card']};
            border: 1px solid {c['border']};
            border-radius: 8px;
        }}
        QFrame#divider {{
            background-color: {c['border']};
            max-height: 1px;
        }}
        """
