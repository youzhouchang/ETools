"""Device manager: browse vendors/MCUs, custom targets, CMSIS packs."""

from __future__ import annotations

import threading

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from etools.core.targets import (
    add_custom_target,
    custom_targets,
    group_targets_by_vendor,
    hidden_targets,
    hidden_vendors,
    hide_target,
    hide_vendor,
    install_pack,
    invalidate_target_cache,
    list_installed_packs,
    list_target_choices,
    remove_custom_target,
    unhide_all_targets,
)
from etools.i18n import tr
from etools.logger import get_logger
from etools.ui.icons import set_button_icon
from etools.ui.ui_loader import embed_form

log = get_logger("ui.devices")

VENDOR_ALL = "*"

# Jobs are not parented to the panel: pack install can outlive the window,
# and destroying a running QThread with its parent crashes Qt.
_LIVE_JOBS: set[_PackJob] = set()
_LIVE_LOCK = threading.Lock()


class _PackJob(QThread):
    """Run `pyocd pack install` or `pyocd pack list` off the GUI thread."""

    finished_ok = Signal(str, object)

    def __init__(self, kind: str, pack_id: str) -> None:
        super().__init__()
        self._kind = kind
        self._pack_id = pack_id

    def run(self) -> None:
        try:
            if self._kind == "install":
                result: object = install_pack(self._pack_id)
            else:
                result = list_installed_packs()
        except Exception as exc:
            result = exc
        self.finished_ok.emit(self._kind, result)


def _release_job(job: _PackJob) -> None:
    with _LIVE_LOCK:
        _LIVE_JOBS.discard(job)
    job.deleteLater()


class DeviceManagerPanel(QWidget):
    """Fourth main tab — manage supported vendors and MCU target list."""

    catalog_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._form = embed_form(self, "device_manager")
        self._bind()
        self._wire()
        self.reload()

    def _bind(self) -> None:
        f = self._form
        self.vendor_list: QListWidget = f.findChild(QListWidget, "vendorList")
        self.device_tree: QTreeWidget = f.findChild(QTreeWidget, "deviceTree")
        self.filter_edit: QLineEdit = f.findChild(QLineEdit, "filterEdit")
        self.refresh_btn: QPushButton = f.findChild(QPushButton, "refreshBtn")
        self.custom_name: QLineEdit = f.findChild(QLineEdit, "customNameEdit")
        self.custom_label: QLineEdit = f.findChild(QLineEdit, "customLabelEdit")
        self.custom_vendor: QLineEdit = f.findChild(QLineEdit, "customVendorEdit")
        self.add_custom_btn: QPushButton = f.findChild(QPushButton, "addCustomBtn")
        self.remove_custom_btn: QPushButton = f.findChild(QPushButton, "removeCustomBtn")
        self.hide_btn: QPushButton = f.findChild(QPushButton, "hideBtn")
        self.hide_vendor_btn: QPushButton = f.findChild(QPushButton, "hideVendorBtn")
        self.unhide_all_btn: QPushButton = f.findChild(QPushButton, "unhideAllBtn")
        self.pack_edit: QLineEdit = f.findChild(QLineEdit, "packEdit")
        self.install_pack_btn: QPushButton = f.findChild(QPushButton, "installPackBtn")
        self.list_pack_btn: QPushButton = f.findChild(QPushButton, "listPackBtn")
        self.hint: QLabel = f.findChild(QLabel, "hintLabel")

        title = f.findChild(QLabel, "panelTitle")
        if title:
            title.setObjectName("panelTitle")
        if self.hint:
            self.hint.setObjectName("hint")
        self.refresh_btn.setObjectName("ghost")
        self.add_custom_btn.setObjectName("accent")
        self.remove_custom_btn.setObjectName("ghost")
        if self.hide_btn is not None:
            self.hide_btn.setObjectName("ghost")
        if self.hide_vendor_btn is not None:
            self.hide_vendor_btn.setObjectName("ghost")
        if self.unhide_all_btn is not None:
            self.unhide_all_btn.setObjectName("ghost")
        self.install_pack_btn.setObjectName("accent")
        self.list_pack_btn.setObjectName("ghost")
        set_button_icon(self.refresh_btn, "refresh", 16)
        set_button_icon(self.add_custom_btn, "chip", 16)
        set_button_icon(self.remove_custom_btn, "clear", 16)
        if self.hide_btn is not None:
            set_button_icon(self.hide_btn, "blank", 16)
        if self.unhide_all_btn is not None:
            set_button_icon(self.unhide_all_btn, "devices", 16)
        set_button_icon(self.install_pack_btn, "save", 16)
        set_button_icon(self.list_pack_btn, "info", 16)

        self.device_tree.setRootIsDecorated(False)
        self.device_tree.setAlternatingRowColors(False)
        self.device_tree.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        self.device_tree.setUniformRowHeights(True)
        self.device_tree.setColumnWidth(0, 180)
        self.device_tree.setColumnWidth(1, 200)
        self.device_tree.setColumnWidth(2, 90)

    def _wire(self) -> None:
        self.refresh_btn.clicked.connect(self.reload)
        self.filter_edit.textChanged.connect(lambda _=None: self._fill_tree())
        self.vendor_list.currentTextChanged.connect(lambda _=None: self._fill_tree())
        self.add_custom_btn.clicked.connect(self._on_add_custom)
        self.remove_custom_btn.clicked.connect(self._on_remove_custom)
        if self.hide_btn is not None:
            self.hide_btn.clicked.connect(self._on_hide_selected)
        if self.hide_vendor_btn is not None:
            self.hide_vendor_btn.clicked.connect(self._on_hide_vendor)
        if self.unhide_all_btn is not None:
            self.unhide_all_btn.clicked.connect(self._on_unhide_all)
        self.install_pack_btn.clicked.connect(self._on_install_pack)
        self.list_pack_btn.clicked.connect(self._on_list_packs)
        self._pack_job: _PackJob | None = None

    # ----- data -----

    def retranslate(self) -> None:
        first = self.vendor_list.item(0)
        if first is not None:
            count = first.text().rsplit(" (", 1)[-1]
            first.setText(f"{tr('devices.all')} ({count}")
        self._fill_tree()

    def reload(self) -> None:
        invalidate_target_cache()
        groups = group_targets_by_vendor()
        self.vendor_list.blockSignals(True)
        self.vendor_list.clear()
        total_n = sum(len(v) for v in groups.values())
        self.vendor_list.addItem(QListWidgetItem(f"{tr('devices.all')} ({total_n})"))
        for vendor in sorted(groups.keys(), key=lambda v: (v == "Other", v)):
            self.vendor_list.addItem(QListWidgetItem(f"{vendor} ({len(groups[vendor])})"))
        self.vendor_list.setCurrentRow(0)
        self.vendor_list.blockSignals(False)
        self._fill_tree()

    def _selected_vendor(self) -> str:
        item = self.vendor_list.currentItem()
        if not item or self.vendor_list.currentRow() <= 0:
            return VENDOR_ALL
        return item.text().rsplit(" (", 1)[0]

    def _fill_tree(self) -> None:
        groups = group_targets_by_vendor()
        vendor = self._selected_vendor()
        keyword = self.filter_edit.text().strip().lower()
        custom_names = {t["name"] for t in custom_targets()}

        # name -> source
        builtin = set()
        try:
            from pyocd.target.builtin import BUILTIN_TARGETS

            builtin = set(BUILTIN_TARGETS.keys())
        except Exception:
            pass

        self.device_tree.clear()
        hidden_n = len(hidden_targets())
        hid_v = len(hidden_vendors())
        items: list[QTreeWidgetItem] = []
        for v, targets in groups.items():
            if vendor != VENDOR_ALL and v != vendor:
                continue
            for name, label in targets:
                model = label.split(" · ", 1)[-1] if " · " in label else label
                if keyword and keyword not in name.lower() and keyword not in label.lower():
                    continue
                if name in custom_names:
                    source = tr("devices.src_custom")
                elif name in builtin:
                    source = tr("devices.src_builtin")
                else:
                    source = tr("devices.src_candidate")
                row = QTreeWidgetItem([model, name, source])
                row.setData(0, Qt.ItemDataRole.UserRole, name)
                items.append(row)
        self.device_tree.addTopLevelItems(items)
        self.hint.setText(
            tr(
                "devices.summary",
                total=len(list_target_choices()),
                custom=len(custom_names),
                hidden=hidden_n,
                hidden_vendors=hid_v,
                vendor=tr("devices.all") if vendor == VENDOR_ALL else vendor,
            )
        )

    # ----- actions -----

    def _on_add_custom(self) -> None:
        name = self.custom_name.text().strip()
        label = self.custom_label.text().strip()
        vendor = self.custom_vendor.text().strip() or "Custom"
        if not name:
            return
        if add_custom_target(name, label, vendor):
            self.custom_name.clear()
            self.custom_label.clear()
            self.custom_vendor.clear()
            self.reload()
            self.catalog_changed.emit()
        else:
            self.hint.setText(tr("devices.add_fail", name=name))

    def _on_remove_custom(self) -> None:
        item = self.device_tree.currentItem()
        if not item:
            return
        name = item.data(0, Qt.ItemDataRole.UserRole) or item.text(1)
        if remove_custom_target(str(name)):
            self.reload()
            self.catalog_changed.emit()
        else:
            self.hint.setText(tr("devices.remove_only_custom"))

    def _selected_target_name(self) -> str:
        item = self.device_tree.currentItem()
        if not item:
            return ""
        return str(item.data(0, Qt.ItemDataRole.UserRole) or item.text(1) or "")

    def _on_hide_selected(self) -> None:
        """Hide currently selected device row (one target)."""
        name = self._selected_target_name()
        if not name:
            self.hint.setText(tr("devices.select_model"))
            return
        if hide_target(name):
            self.reload()
            self.catalog_changed.emit()
            self.hint.setText(tr("devices.hidden_model", name=name))
        else:
            self.hint.setText(tr("devices.hide_fail", name=name))

    def _on_hide_vendor(self) -> None:
        """Hide the currently selected vendor (all its targets)."""
        vendor = self._selected_vendor()
        if not vendor or vendor == VENDOR_ALL:
            self.hint.setText(tr("devices.select_vendor"))
            return
        if hide_vendor(vendor):
            n = self.vendor_list.currentItem().text() if self.vendor_list.currentItem() else ""
            self.reload()
            self.catalog_changed.emit()
            self.hint.setText(tr("devices.hidden_vendor", vendor=vendor, n=n))
        else:
            self.hint.setText(tr("devices.hide_vendor_fail", vendor=vendor))

    def _on_unhide_all(self) -> None:
        unhide_all_targets()
        self.reload()
        self.catalog_changed.emit()
        self.hint.setText(tr("devices.unhidden"))

    def shutdown(self) -> None:
        """Drop the result handler. A running pack job is left to finish on its own."""
        job = self._pack_job
        self._pack_job = None
        if job is None:
            return
        try:
            job.finished_ok.disconnect(self._apply_pack)
        except (RuntimeError, TypeError):
            pass

    def _on_install_pack(self) -> None:
        pack = self.pack_edit.text().strip()
        if not pack:
            self.hint.setText(tr("devices.pack_need_id"))
            return
        if not self._start_pack_job("install", pack):
            return
        self.hint.setText(tr("devices.pack_installing", pack=pack))

    def _on_list_packs(self) -> None:
        if not self._start_pack_job("list"):
            return
        self.hint.setText(tr("devices.pack_listing"))

    def _start_pack_job(self, kind: str, pack_id: str = "") -> bool:
        if self._pack_job is not None and self._pack_job.isRunning():
            return False
        job = _PackJob(kind, pack_id)
        with _LIVE_LOCK:
            _LIVE_JOBS.add(job)
        job.finished_ok.connect(self._apply_pack)
        job.finished.connect(lambda j=job: _release_job(j))
        self._pack_job = job
        self._set_pack_busy(True)
        job.start()
        return True

    def _set_pack_busy(self, busy: bool) -> None:
        self.install_pack_btn.setEnabled(not busy)
        self.list_pack_btn.setEnabled(not busy)

    def _apply_pack(self, kind: str, result: object) -> None:
        if self._pack_job is None:
            return
        self._pack_job = None
        self._set_pack_busy(False)
        if kind == "install":
            self._show_install_result(result)
            return
        self._show_pack_list(result)

    def _show_install_result(self, result: object) -> None:
        if not (isinstance(result, tuple) and len(result) == 2):
            self.hint.setText(tr("devices.pack_error", err=result))
            return
        ok, msg = result
        if ok:
            self.reload()
            self.catalog_changed.emit()
        last = str(msg).splitlines()[-1] if msg else ""
        self.hint.setText(tr("devices.pack_ok" if ok else "devices.pack_fail", msg=last))

    def _show_pack_list(self, result: object) -> None:
        if not isinstance(result, list):
            self.hint.setText(tr("devices.pack_list_fail", err=result))
            return
        lines = result
        self.vendor_list.blockSignals(True)
        self.vendor_list.setCurrentRow(0)
        self.vendor_list.blockSignals(False)
        self.device_tree.clear()
        if not lines:
            self.hint.setText(tr("devices.pack_none"))
            return
        for ln in lines:
            self.device_tree.addTopLevelItem(QTreeWidgetItem([ln[:80], ln, "Pack"]))
        self.hint.setText(tr("devices.pack_count", n=len(lines)))
