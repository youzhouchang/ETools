"""One-row tab strip that shows a single optional panel."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class SectionTabs(QWidget):
    """Checkable tabs on one line. Click the open tab again to collapse it."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._buttons: list[QToolButton] = []
        self._pages: list[QWidget] = []
        self._bar = QHBoxLayout()
        self._bar.setSpacing(2)
        self._bar.setContentsMargins(0, 0, 0, 0)
        self._stack = QStackedWidget()
        self._stack.setVisible(False)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addLayout(self._bar)
        self._bar.addStretch(1)
        lay.addWidget(self._stack)

    def add_page(self, title: str, page: QWidget, tip: str = "") -> QToolButton:
        button = QToolButton()
        button.setObjectName("sectionTab")
        button.setCheckable(True)
        button.setText(title)
        button.setToolTip(tip)
        button.setAutoRaise(True)
        button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        button.clicked.connect(lambda _checked=False, btn=button: self._on_clicked(btn))
        # Keep the stretch at the end.
        self._bar.insertWidget(self._bar.count() - 1, button)
        self._buttons.append(button)
        self._pages.append(page)
        self._stack.addWidget(page)
        return button

    def show_page(self, index: int) -> None:
        """Open one tab. A script can reveal the plot without a click."""
        if not 0 <= index < len(self._buttons):
            return
        button = self._buttons[index]
        button.setChecked(True)
        self._on_clicked(button)

    def set_title(self, index: int, title: str, tip: str = "") -> None:
        button = self._buttons[index]
        button.setText(title)
        if tip:
            button.setToolTip(tip)

    def _on_clicked(self, button: QToolButton) -> None:
        index = self._buttons.index(button)
        if button.isChecked():
            for other in self._buttons:
                if other is not button:
                    other.setChecked(False)
            self._stack.setCurrentIndex(index)
            self._stack.setVisible(True)
        else:
            self._stack.setVisible(False)
        open_index = index if self._stack.isVisible() else -1
        for i, page in enumerate(self._pages):
            mark = getattr(page, "set_section_open", None)
            if mark is not None:
                mark(i == open_index)
