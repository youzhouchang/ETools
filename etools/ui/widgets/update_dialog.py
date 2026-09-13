"""Update-available dialog: Markdown release notes + direct download."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QStandardPaths, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from etools.core.updater import (
    UpdateInfo,
    apply_update,
    can_auto_install,
    default_save_name,
    download_file,
    is_frozen,
    pick_best_asset,
)
from etools.i18n import tr
from etools.logger import get_logger
from etools.ui.markdown import markdown_document
from etools.ui.styles import Theme, get_theme

log = get_logger("ui.update_dialog")


class _AssetDownloader(QObject):
    """Download one release asset on a worker thread."""

    progressed = Signal(int, int)
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, url: str, dest: str) -> None:
        super().__init__()
        self._url = url
        self._dest = dest

    def run(self) -> None:
        try:
            path = download_file(
                self._url,
                Path(self._dest),
                progress=lambda r, t: self.progressed.emit(r, t),
            )
            self.finished.emit(str(path))
        except Exception as exc:  # noqa: BLE001
            log.exception("download failed")
            self.failed.emit(str(exc))


def _dialog_stylesheet(theme: Theme) -> str:
    """Local QSS so the dialog matches the app theme even without app sheet."""
    return f"""
    QDialog {{
        background: {theme.bg};
        color: {theme.text};
    }}
    QLabel {{
        color: {theme.text};
        background: transparent;
    }}
    QLabel#updateHead {{
        font-size: 14px;
        font-weight: 600;
        color: {theme.text};
    }}
    QLabel#updateHint {{
        color: {theme.text_dim};
    }}
    QTextBrowser {{
        background: {theme.bg_input};
        color: {theme.text};
        border: 1px solid {theme.border};
        border-radius: 6px;
        padding: 6px 8px;
        selection-background-color: {theme.accent};
        selection-color: {theme.on_accent};
    }}
    QTextBrowser a {{ color: {theme.accent}; }}
    QPushButton {{
        background: {theme.bg_input};
        color: {theme.text};
        border: 1px solid {theme.border};
        border-radius: 5px;
        padding: 5px 12px;
        min-height: 18px;
    }}
    QPushButton:hover {{
        background: {theme.bg_hover};
        border-color: {theme.accent};
    }}
    QPushButton:pressed {{ background: {theme.bg_panel}; }}
    QPushButton#accent {{
        background: {theme.accent};
        color: {theme.on_accent};
        border: none;
        font-weight: 600;
        padding: 7px 14px;
    }}
    QPushButton#accent:hover {{ background: {theme.accent_hover}; }}
    QDialogButtonBox QPushButton {{ min-width: 72px; }}
    QProgressDialog {{
        background: {theme.bg};
        color: {theme.text};
    }}
    QProgressDialog QLabel {{
        color: {theme.text};
        background: transparent;
    }}
    QMessageBox {{
        background: {theme.bg};
        color: {theme.text};
    }}
    QMessageBox QLabel {{
        color: {theme.text};
        background: transparent;
    }}
    """


class UpdateAvailableDialog(QDialog):
    """Show release notes (Markdown rendered) and offer a direct download."""

    def __init__(self, info: UpdateInfo, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.info = info
        self.asset = pick_best_asset(info.assets)
        self.downloaded_path: str | None = None
        self.install_started = False

        # Always resolve from live config so light/dark matches the app.
        theme = get_theme()
        self._theme = theme
        self.setStyleSheet(_dialog_stylesheet(theme))

        self.setWindowTitle(tr("update.title"))
        self.setMinimumSize(520, 420)
        self.resize(560, 480)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 12)
        root.setSpacing(10)

        head = QLabel(tr("update.available", latest=info.latest, current=info.current))
        head.setObjectName("updateHead")
        head.setWordWrap(True)
        root.addWidget(head)

        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        self.browser.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.browser.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = info.body or tr("update.no_notes")
        self.browser.setHtml(
            markdown_document(
                body,
                text_color=theme.text,
                link_color=theme.accent,
                code_bg=theme.bg_hover if theme.name == "dark" else theme.bg_input,
            )
        )
        root.addWidget(self.browser, 1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.download_btn: QPushButton | None = None
        if self.asset and self.asset.get("browser_download_url"):
            self.download_btn = QPushButton(tr("update.download"))
            self.download_btn.setObjectName("accent")
            self.download_btn.setDefault(True)
            self.download_btn.setAutoDefault(True)
            self.download_btn.clicked.connect(self._start_download)
            btn_row.addWidget(self.download_btn)
        else:
            note = QLabel(tr("update.no_asset"))
            note.setObjectName("updateHint")
            note.setWordWrap(True)
            btn_row.addWidget(note, 1)

        if info.html_url:
            open_btn = QPushButton(tr("update.open"))
            open_btn.clicked.connect(self._open_release_page)
            btn_row.addWidget(open_btn)

        btn_row.addStretch(1)
        root.addLayout(btn_row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        root.addWidget(buttons)

        self._dl_thread: QThread | None = None
        self._dl_worker: _AssetDownloader | None = None
        self._progress: QProgressDialog | None = None

    def _open_release_page(self) -> None:
        if self.info.html_url:
            QDesktopServices.openUrl(QUrl(self.info.html_url))

    def _start_download(self) -> None:
        if self.asset is None:
            return
        url = str(self.asset.get("browser_download_url") or "")
        if not url:
            return
        name = default_save_name(self.asset)
        from PySide6.QtWidgets import QFileDialog

        default_dir = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DownloadLocation
        ) or str(Path.home())
        dest, _ = QFileDialog.getSaveFileName(
            self, tr("update.save_title"), str(Path(default_dir) / name)
        )
        if not dest:
            return

        self._progress = QProgressDialog(
            tr("update.downloading"), tr("update.cancel"), 0, 0, self
        )
        self._progress.setWindowTitle(tr("update.title"))
        self._progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._progress.setAutoClose(False)
        self._progress.setAutoReset(False)
        self._progress.setStyleSheet(_dialog_stylesheet(self._theme))
        self._progress.canceled.connect(self._cancel_download)
        self._progress.show()

        thread = QThread(self)
        worker = _AssetDownloader(url, dest)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progressed.connect(self._on_dl_progress)
        worker.finished.connect(self._on_dl_done)
        worker.failed.connect(self._on_dl_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._dl_thread = thread
        self._dl_worker = worker
        thread.start()

    def _cancel_download(self) -> None:
        # urllib is not easily interruptible mid-chunk; drop the dialog reference.
        if self._progress is not None:
            self._progress = None

    def _on_dl_progress(self, received: int, total: int) -> None:
        if self._progress is None:
            return
        if total > 0:
            if self._progress.maximum() != 100:
                self._progress.setMaximum(100)
            self._progress.setValue(min(100, int(received * 100 / total)))
            self._progress.setLabelText(
                tr("update.downloading_pct", pct=int(received * 100 / total))
            )
        else:
            self._progress.setMaximum(0)
            mb = max(received, 0) // (1024 * 1024)
            self._progress.setLabelText(tr("update.downloading_mb", mb=mb))

    def _on_dl_done(self, path: str) -> None:
        if self._progress is not None:
            self._progress.close()
            self._progress = None
        self.downloaded_path = path

        if can_auto_install(path) and is_frozen():
            self._offer_auto_install(path)
            return

        box = QMessageBox(
            QMessageBox.Icon.Information,
            tr("update.title"),
            tr("update.source_only", path=path)
            if not is_frozen()
            else tr("update.download_done", path=path),
            QMessageBox.StandardButton.Ok,
            self,
        )
        box.setStyleSheet(_dialog_stylesheet(self._theme))
        box.exec()
        self.accept()

    def _offer_auto_install(self, path: str) -> None:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(tr("update.title"))
        box.setText(tr("update.install_confirm"))
        box.setInformativeText(path)
        yes = box.addButton(tr("update.install_now"), QMessageBox.ButtonRole.AcceptRole)
        yes.setObjectName("accent")
        box.addButton(tr("update.install_later"), QMessageBox.ButtonRole.RejectRole)
        box.setStyleSheet(_dialog_stylesheet(self._theme))
        box.exec()
        if box.clickedButton() is not yes:
            # Keep package on disk; just close.
            done = QMessageBox(
                QMessageBox.Icon.Information,
                tr("update.title"),
                tr("update.download_done", path=path),
                QMessageBox.StandardButton.Ok,
                self,
            )
            done.setStyleSheet(_dialog_stylesheet(self._theme))
            done.exec()
            self.accept()
            return

        try:
            apply_update(Path(path))
        except Exception as exc:  # noqa: BLE001
            log.exception("auto install failed")
            fail = QMessageBox(
                QMessageBox.Icon.Warning,
                tr("update.title"),
                tr("update.install_failed", err=str(exc)),
                QMessageBox.StandardButton.Ok,
                self,
            )
            fail.setStyleSheet(_dialog_stylesheet(self._theme))
            fail.exec()
            return

        self.install_started = True
        info = QMessageBox(
            QMessageBox.Icon.Information,
            tr("update.title"),
            tr("update.restarting"),
            QMessageBox.StandardButton.Ok,
            self,
        )
        info.setStyleSheet(_dialog_stylesheet(self._theme))
        info.exec()
        self.accept()
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _on_dl_failed(self, message: str) -> None:
        if self._progress is not None:
            self._progress.close()
            self._progress = None
        box = QMessageBox(
            QMessageBox.Icon.Warning,
            tr("update.title"),
            tr("update.download_failed", err=message),
            QMessageBox.StandardButton.Ok,
            self,
        )
        box.setStyleSheet(_dialog_stylesheet(self._theme))
        box.exec()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._dl_thread is not None and self._dl_thread.isRunning():
            self._dl_thread.requestInterruption()
        super().closeEvent(event)
