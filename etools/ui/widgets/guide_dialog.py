"""In-app user guide. The text lives in docs/guide.md."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QTextBrowser, QVBoxLayout

from etools.i18n import tr
from etools.ui.guide_doc import load_guide
from etools.ui.markdown import markdown_document
from etools.ui.styles import get_theme


class GuideDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("guide.title"))
        self.resize(760, 640)
        self.setMinimumSize(480, 360)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 12)
        root.setSpacing(10)

        browser = QTextBrowser()
        browser.setOpenExternalLinks(False)
        browser.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        browser.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        theme = get_theme()
        try:
            body = load_guide()
        except OSError:
            body = tr("guide.missing")
        browser.setHtml(
            markdown_document(
                body,
                text_color=theme.text,
                link_color=theme.accent,
                code_bg=theme.bg_hover if theme.name == "dark" else theme.bg_input,
            )
        )
        root.addWidget(browser, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        root.addWidget(buttons)
