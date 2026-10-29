"""ETools application entry point."""

from __future__ import annotations

import sys
import traceback


def _text(key: str, zh: str, en: str, **kwargs) -> str:
    """Translated text; falls back to both languages when i18n cannot load."""
    try:
        from etools.i18n import tr

        text = tr(key, **kwargs)
        if text != key:
            return text
    except Exception:  # noqa: BLE001
        pass
    return f"{zh.format(**kwargs)}\n{en.format(**kwargs)}"


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
        _show_fatal(_text("app.fatal_error", "ETools 发生错误", "ETools error"), msg[-4000:])

    sys.excepthook = hook


def python_too_old_message() -> str | None:
    """Explain a base-conda style launch before imports hit runtime subscripts."""
    # Runtime guard: conda base can be older than requires-python.
    if sys.version_info >= (3, 10):  # noqa: UP036
        return None
    # i18n cannot be imported on old interpreters, so this text is bilingual.
    version = sys.version.split()[0]
    return (
        "ETools 需要 Python 3.10 或更新版本。\n"
        f"当前解释器是 {version}（{sys.executable}）。\n"
        "请换到已安装依赖的 etools 环境后再运行：\n\n"
        "ETools needs Python 3.10 or newer.\n"
        f"The current interpreter is {version} ({sys.executable}).\n"
        "Switch to the etools environment with the dependencies installed:\n\n"
        "conda activate etools\n"
        "python -m etools"
    )


def main() -> int:
    _install_excepthook()
    too_old = python_too_old_message()
    if too_old:
        _show_fatal("ETools 无法启动 / ETools cannot start", too_old)
        return 1

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
        _show_fatal(
            _text("app.start_failed", "ETools 启动失败", "ETools failed to start"),
            _text("app.import_failed", "导入模块失败：\n{err}", "Import failed:\n{err}", err=exc),
        )
        return 1

    import logging

    level_name = get_config().log_level.upper()
    level = getattr(logging, level_name, logging.INFO)
    setup_logging(level)

    try:
        app = QApplication(sys.argv)
        app.setApplicationName(__app_name__)
        app.setOrganizationName("ETools")
        # Helps X11 WM_CLASS / some docks group windows correctly
        if hasattr(app, "setDesktopFileName"):
            # Must match .desktop basename (etools.desktop) and Icon=etools
            app.setDesktopFileName("etools")
        app.setStyle("Fusion")

        from etools.ui.qt_messages import install_qt_message_bridge

        install_qt_message_bridge()

        from etools.ui.icons import app_icon

        icon = app_icon()
        if not icon.isNull():
            app.setWindowIcon(icon)

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
        title = _text("app.start_failed", "ETools 启动失败", "ETools failed to start")
        _show_fatal(title, f"{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
