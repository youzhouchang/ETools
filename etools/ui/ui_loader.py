"""Load Qt Designer .ui forms."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QFile, Qt
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

FORMS_DIR = Path(__file__).resolve().parent / "forms"


def form_path(name: str) -> Path:
    p = FORMS_DIR / f"{name}.ui"
    if not p.exists():
        raise FileNotFoundError(f"UI form not found: {p}")
    return p


def load_form(name: str, parent: QWidget | None = None) -> QWidget:
    """Load forms/<name>.ui and return the root widget."""
    path = form_path(name)
    file = QFile(str(path))
    if not file.open(QFile.OpenModeFlag.ReadOnly):
        raise RuntimeError(f"Cannot open UI form: {path}")
    try:
        loader = QUiLoader()
        root = loader.load(file, parent)
    finally:
        file.close()
    if root is None:
        raise RuntimeError(f"QUiLoader failed to load {path}")
    return root


def embed_form(host: QWidget, name: str) -> QWidget:
    """Load a form and place it as the only child of *host*.

    Host keeps a zero-margin layout so objectName/styles from .ui still apply
    on the form root; all logic finds children via findChild.
    """
    form = load_form(name, host)
    lay = host.layout()
    if lay is None:
        lay = QVBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    # clear any existing items
    while lay.count():
        item = lay.takeAt(0)
        w = item.widget()
        if w is not None:
            w.deleteLater()
    lay.addWidget(form)
    # Expand to fill the host (e.g. log view reaches the bottom).
    # Do not set AlignTop here — alignment disables widget expansion.
    form.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    return form
