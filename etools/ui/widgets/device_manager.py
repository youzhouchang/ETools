"""Device manager: browse vendors/MCUs, custom targets, CMSIS packs."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
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

VENDOR_ALL = "全部"


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

    # ----- data -----

    def reload(self) -> None:
        invalidate_target_cache()
        groups = group_targets_by_vendor()
        self.vendor_list.blockSignals(True)
        self.vendor_list.clear()
        total_n = sum(len(v) for v in groups.values())
        self.vendor_list.addItem(QListWidgetItem(f"{VENDOR_ALL} ({total_n})"))
        for vendor in sorted(groups.keys(), key=lambda v: (v == "Other", v)):
            self.vendor_list.addItem(QListWidgetItem(f"{vendor} ({len(groups[vendor])})"))
        self.vendor_list.setCurrentRow(0)
        self.vendor_list.blockSignals(False)
        self._fill_tree()

    def _selected_vendor(self) -> str:
        item = self.vendor_list.currentItem()
        if not item:
            return VENDOR_ALL
        text = item.text()
        if text.startswith(VENDOR_ALL):
            return VENDOR_ALL
        return text.rsplit(" (", 1)[0]

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
                    source = "自定义"
                elif name in builtin:
                    source = "内置"
                else:
                    source = "候选"
                row = QTreeWidgetItem([model, name, source])
                row.setData(0, Qt.ItemDataRole.UserRole, name)
                items.append(row)
        self.device_tree.addTopLevelItems(items)
        self.hint.setText(
            f"共 {len(list_target_choices())} 个 target · 自定义 {len(custom_names)} · "
            f"隐藏型号 {hidden_n} · 隐藏厂商 {hid_v} · 当前筛选：{vendor}"
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
            self.hint.setText(f"已存在或无效：{name}")

    def _on_remove_custom(self) -> None:
        item = self.device_tree.currentItem()
        if not item:
            return
        name = item.data(0, Qt.ItemDataRole.UserRole) or item.text(1)
        if remove_custom_target(str(name)):
            self.reload()
            self.catalog_changed.emit()
        else:
            self.hint.setText("仅自定义项可删除；内置项请用「隐藏选中」")

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
            self.hint.setText(f"已隐藏型号 {name}")
        else:
            self.hint.setText(f"无法隐藏 {name}")

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
            self.hint.setText(f"已隐藏厂商 {vendor}（{n}）")
        else:
            self.hint.setText(f"无法隐藏厂商 {vendor}")

    def _on_unhide_all(self) -> None:
        unhide_all_targets()
        self.reload()
        self.catalog_changed.emit()
        self.hint.setText("已恢复全部隐藏的型号与厂商")

    def _on_install_pack(self) -> None:
        pack = self.pack_edit.text().strip()
        if not pack:
            self.hint.setText("请填写 Pack ID，例如 GigaDevice::GD32F103C8，再点「安装 Pack」")
            return
        self.hint.setText(f"正在安装 {pack} …（可能需要联网，最长约 2 分钟）")
        self.install_pack_btn.setEnabled(False)
        self.list_pack_btn.setEnabled(False)
        try:
            ok, msg = install_pack(pack)
            last = msg.splitlines()[-1] if msg else pack
            self.hint.setText(("安装成功：" if ok else "安装失败：") + last)
            if ok:
                self.reload()
                self.catalog_changed.emit()
        except Exception as exc:
            self.hint.setText(f"安装异常：{exc}")
        finally:
            self.install_pack_btn.setEnabled(True)
            self.list_pack_btn.setEnabled(True)

    def _on_list_packs(self) -> None:
        self.hint.setText("正在查询已装 Pack…")
        self.list_pack_btn.setEnabled(False)
        self.install_pack_btn.setEnabled(False)
        try:
            lines = list_installed_packs()
        except Exception as exc:
            lines = []
            self.hint.setText(f"查询失败：{exc}")
        finally:
            self.list_pack_btn.setEnabled(True)
            self.install_pack_btn.setEnabled(True)

        self.vendor_list.blockSignals(True)
        self.vendor_list.setCurrentRow(0)
        self.vendor_list.blockSignals(False)
        self.device_tree.clear()
        if not lines:
            self.hint.setText(
                "未列出已装 Pack（pyocd 不可用或列表为空）。可尝试：python -m pyocd pack list"
            )
            return
        for ln in lines:
            self.device_tree.addTopLevelItem(QTreeWidgetItem([ln[:80], ln, "Pack"]))
        self.hint.setText(f"已装 Pack 共 {len(lines)} 行（python -m pyocd pack list）")
