"""Project profile management."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from etools.core import project_profiles as store
from etools.i18n import tr


class ProjectDialog(QDialog):
    def __init__(self, capture, apply, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("project.title"))
        self.resize(540, 360)
        self._capture = capture
        self._apply = apply
        layout = QVBoxLayout(self)
        self.entries = QListWidget()
        layout.addWidget(self.entries)
        row = QHBoxLayout()
        for key, slot in (
            ("save", self._save),
            ("copy", self._copy),
            ("apply", self._activate),
            ("import", self._import),
            ("export", self._export),
        ):
            button = QPushButton(tr("project." + key))
            button.clicked.connect(slot)
            row.addWidget(button)
        layout.addLayout(row)
        self._refresh()

    def _refresh(self, name=""):
        self.entries.clear()
        self.entries.addItems(sorted(store.profiles()))
        matches = self.entries.findItems(name, Qt.MatchFlag.MatchExactly)
        if matches:
            self.entries.setCurrentItem(matches[0])

    def _selected(self):
        item = self.entries.currentItem()
        return item.text() if item else ""

    def _name(self, initial=""):
        name, ok = QInputDialog.getText(self, tr("project.title"), tr("project.name"), text=initial)
        return name.strip() if ok else ""

    def _store(self, name, payload):
        if not name:
            return
        if (
            name in store.profiles()
            and QMessageBox.question(
                self,
                tr("project.title"),
                tr("project.overwrite", name=name),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            store.save_profile(name, payload)
            self._refresh(name)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, tr("project.title"), str(exc))

    def _save(self):
        self._store(self._name(self._selected()), self._capture())

    def _copy(self):
        name = self._selected()
        if name:
            self._store(self._name(name + " copy"), store.profiles()[name])

    def _activate(self):
        name = self._selected()
        if name:
            try:
                self._apply(store.profiles()[name])
                self.accept()
            except (ValueError, RuntimeError, OSError) as exc:
                QMessageBox.warning(self, tr("project.title"), str(exc))

    def _import(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("project.import"), "", "JSON (*.json)")
        if path:
            try:
                self._store(self._name(), store.import_profile(path))
            except (ValueError, OSError) as exc:
                QMessageBox.warning(self, tr("project.title"), str(exc))

    def _export(self):
        name = self._selected()
        if not name:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, tr("project.export"), name + ".json", "JSON (*.json)"
        )
        if path:
            try:
                store.export_profile(path, store.profiles()[name])
            except (ValueError, OSError) as exc:
                QMessageBox.warning(self, tr("project.title"), str(exc))
