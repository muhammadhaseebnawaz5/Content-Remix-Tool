#!/usr/bin/env python3
"""
AI Bulk Remix Studio v1.0.0
Professional Desktop Application for Bulk Video Remixing

Entry point: Initializes PySide6 QApplication and MainWindow.
"""

import sys
import os
import argparse

# Ensure src is importable
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import Qt, QCoreApplication
from src.ui.main_window import MainWindow
from src.utils.logger import setup_logger


def exception_hook(exc_type, exc_value, exc_traceback):
    """Global exception handler for uncaught exceptions."""
    import traceback
    logger = setup_logger()
    logger.error("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))
    traceback.print_exception(exc_type, exc_value, exc_traceback)


def main():
    parser = argparse.ArgumentParser(description="AI Bulk Remix Studio")
    parser.add_argument("--theme", choices=["dark", "light"], help="Force theme mode")
    parser.add_argument("--project", help="Open project file on startup")
    args = parser.parse_args()


    app = QApplication(sys.argv)
    app.setApplicationName("AI Bulk Remix Studio")
    app.setApplicationVersion("1.0.0")
    app.setOrganizationName("AIBRS")
    app.setOrganizationDomain("aibrs.local")

    # Global exception hook
    sys.excepthook = exception_hook

    # Setup logging
    log_dir = os.path.join(BASE_DIR, "logs")
    os.makedirs(log_dir, exist_ok=True)
    logger = setup_logger(level="INFO", log_dir=log_dir)
    logger.info("=" * 50)
    logger.info("AI Bulk Remix Studio v1.0.0 starting...")
    logger.info(f"Base directory: {BASE_DIR}")
    logger.info(f"Python: {sys.version}")
    logger.info(f"Platform: {sys.platform}")
    logger.info("=" * 50)

    try:
        window = MainWindow()
        
        if args.theme:
            if args.theme != window._theme.mode:
                window._toggle_theme()
        
        if args.project and os.path.exists(args.project):
            window._project.load(args.project)
            logger.info(f"Loaded project: {args.project}")
        
        window.show()
        logger.info("MainWindow displayed successfully.")
        
        exit_code = app.exec()
        logger.info(f"Application exiting with code {exit_code}")
        sys.exit(exit_code)
        
    except Exception as e:
        logger.critical(f"Failed to start application: {e}", exc_info=True)
        QMessageBox.critical(None, "Startup Error",
            f"Failed to start AI Bulk Remix Studio:\n\n{str(e)}\n\n"
            "Please check the logs for more details.")
        sys.exit(1)


if __name__ == "__main__":
    main()
