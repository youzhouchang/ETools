"""ETools application entry point."""

from __future__ import annotations

import sys
import traceback


def _show_fatal(title: str, text: str) -> None:
    """Best-effort GUI error dialog (works even if main window failed)."""
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        app = QApplication.instance()
        owned = False
        if app is None:
            app = QApplication(sys.argv)
            owned = True
        QMessageBox.critical(None, title, text)
        if owned:
            app.processEvents()
    except Exception:
        sys.stderr.write(f"{title}\n{text}\n")


def _install_excepthook() -> None:
    def hook(exc_type, exc, tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        msg = "".join(traceback.format_exception(exc_type, exc, tb))
        sys.stderr.write(msg)
        try:
            from etools.logger import get_logger

            get_logger("app").error("Unhandled exception:\n%s", msg)
        except Exception:
            pass
        _show_fatal("ETools 发生错误", msg[-4000:])

    sys.excepthook = hook


def main() -> int:
    _install_excepthook()

    try:
        from PySide6.QtGui import QFont
        from PySide6.QtWidgets import QApplication

        from etools import __app_name__
        from etools.config import get_config
        from etools.logger import setup_logging
        from etools.ui.main_window import MainWindow
        from etools.ui.styles import build_stylesheet
    except Exception as exc:
        traceback.print_exc()
        _show_fatal("ETools 启动失败", f"导入模块失败：\n{exc}")
        return 1

    import logging

    level_name = get_config().log_level.upper()
    level = getattr(logging, level_name, logging.INFO)
    setup_logging(level)

    try:
        app = QApplication(sys.argv)
        app.setApplicationName(__app_name__)
        app.setOrganizationName("ETools")
        app.setStyle("Fusion")

        from etools.ui.icons import app_icon

        app.setWindowIcon(app_icon())
        # Match .desktop Icon=etools so GNOME/KDE dock groups the window correctly
        if sys.platform.startswith("linux"):
            app.setDesktopFileName("etools")

        font = QFont("Segoe UI", 10)
        if sys.platform == "darwin":
            font = QFont("SF Pro Text", 13)
        elif sys.platform.startswith("linux"):
            font = QFont("Noto Sans", 10)
        app.setFont(font)
        app.setStyleSheet(build_stylesheet(get_config().theme))

        window = MainWindow()
        window.show()
        return app.exec()
    except Exception as exc:
        traceback.print_exc()
        _show_fatal("ETools 启动失败", f"{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
