"""Lightweight i18n for ETools UI (zh-CN default, en optional)."""

from __future__ import annotations

from etools.config import get_config, save_config

LANG_ZH = "zh"
LANG_EN = "en"

_STRINGS: dict[str, dict[str, str]] = {
    LANG_ZH: {
        "menu.file": "文件(&F)",
        "menu.firmware": "固件(&W)",
        "menu.view": "视图(&V)",
        "menu.help": "帮助(&H)",
        "menu.language": "语言(&L)",
        "menu.theme": "主题(&T)",
        "act.open": "打开固件…",
        "act.quit": "退出",
        "act.program": "烧录",
        "act.erase": "全片擦除",
        "act.verify": "校验",
        "act.reset": "复位",
        "act.read_chip": "读取芯片到 Hex",
        "act.theme_dark": "深色主题",
        "act.theme_light": "浅色主题",
        "act.hex": "Hex 预览",
        "act.about": "关于 ETools",
        "act.check_update": "检查更新…",
        "act.lang_zh": "中文",
        "act.lang_en": "English",
        "update.checking": "正在检查更新…",
        "update.available": "发现新版本 {latest}（当前 {current}）",
        "update.latest": "已是最新版本（{current}）",
        "update.failed": "检查更新失败（网络或 GitHub 不可用）",
        "update.title": "检查更新",
        "update.open": "打开发布页",
        "update.download": "下载更新",
        "update.no_notes": "（本版本未提供更新说明）",
        "update.no_asset": "未找到适合当前系统的安装包，请打开发布页手动下载。",
        "update.save_title": "保存安装包",
        "update.downloading": "正在下载…",
        "update.downloading_pct": "正在下载… {pct}%",
        "update.downloading_mb": "已下载 {mb} MB…",
        "update.cancel": "取消",
        "update.download_done": "下载完成：\n{path}",
        "update.download_failed": "下载失败：{err}",
        "update.install_confirm": "更新包已下载完成。\n\n是否立即安装并重启 ETools？",
        "update.install_now": "立即安装",
        "update.install_later": "稍后手动安装",
        "update.installing": "正在启动安装，请按提示完成升级…",
        "update.install_failed": "启动自动升级失败：{err}",
        "update.source_only": (
            "已下载安装包（源码运行无法自动覆盖）：\n{path}\n\n请手动安装或替换后重启。"
        ),
        "update.restarting": "ETools 即将退出以完成升级…",
        "log.update_available": "发现新版本：{latest}",
        "log.update_latest": "当前已是最新版本",
        "log.update_failed": "检查更新失败",
        "log.update_downloaded": "更新包已下载：{path}",
        "log.update_installing": "已启动自动升级，应用即将退出",
        "about.github": "GitHub 仓库",
        "tb.main": "主工具栏",
        "tab.info": "目标信息",
        "tab.hex": "Hex 预览",
        "tab.flash": "固件操作",
        "tab.devices": "设备管理",
        "tab.rtt": "RTT View",
        "tab.swo": "SWV",
        "hex.title": "Hex 预览",
        "hex.open": "打开文件…",
        "hex.addr": "地址",
        "hex.size": "长度",
        "hex.read": "读芯片",
        "hex.mem": "内存信息",
        "hex.plus_tip": "点击 + 打开新文件",
        "hex.read_by_size": "按长度读取",
        "hex.read_all": "读取全部",
        "hex.save_as": "另存为…",
        "hex.fill": "填充内存",
        "hex.blank": "空白检查",
        "hex.cmp_file": "与文件比较",
        "hex.cmp_two": "比较两个文件",
        "status.connected": "已连接",
        "status.disconnected": "未连接",
        "status.connecting": "连接中…",
        "status.failed": "连接失败",
        "log.lang_switched": "界面语言已切换",
        "log.theme_dark": "已切换主题：深色",
        "log.theme_light": "已切换主题：浅色",
        "about.text": "ETools {ver}\n嵌入式 MCU 烧录工具\n后端：pyOCD\n\n{github}",
    },
    LANG_EN: {
        "menu.file": "&File",
        "menu.firmware": "Firm&ware",
        "menu.view": "&View",
        "menu.help": "&Help",
        "menu.language": "&Language",
        "menu.theme": "T&heme",
        "act.open": "Open Firmware…",
        "act.quit": "Quit",
        "act.program": "Program",
        "act.erase": "Mass Erase",
        "act.verify": "Verify",
        "act.reset": "Reset",
        "act.read_chip": "Read Chip to Hex",
        "act.theme_dark": "Dark Theme",
        "act.theme_light": "Light Theme",
        "act.hex": "Hex Preview",
        "act.about": "About ETools",
        "act.check_update": "Check for Updates…",
        "act.lang_zh": "中文",
        "act.lang_en": "English",
        "update.checking": "Checking for updates…",
        "update.available": "New version {latest} available (current {current})",
        "update.latest": "You are up to date ({current})",
        "update.failed": "Update check failed (network or GitHub unavailable)",
        "update.title": "Check for Updates",
        "update.open": "Open release page",
        "update.download": "Download update",
        "update.no_notes": "(No release notes for this version)",
        "update.no_asset": "No package for this OS. Open the release page to download manually.",
        "update.save_title": "Save installer",
        "update.downloading": "Downloading…",
        "update.downloading_pct": "Downloading… {pct}%",
        "update.downloading_mb": "Downloaded {mb} MB…",
        "update.cancel": "Cancel",
        "update.download_done": "Download complete:\n{path}",
        "update.download_failed": "Download failed: {err}",
        "update.install_confirm": "Update package downloaded.\n\nInstall and restart ETools now?",
        "update.install_now": "Install now",
        "update.install_later": "Install later",
        "update.installing": "Starting installer…",
        "update.install_failed": "Failed to start auto-update: {err}",
        "update.source_only": (
            "Package saved (source run cannot auto-replace):\n{path}\n\n"
            "Install or replace manually, then restart."
        ),
        "update.restarting": "ETools will exit to finish the upgrade…",
        "log.update_available": "Update available: {latest}",
        "log.update_latest": "Already up to date",
        "log.update_failed": "Update check failed",
        "log.update_downloaded": "Update package saved: {path}",
        "log.update_installing": "Auto-update started; app will exit",
        "about.github": "GitHub repository",
        "tb.main": "Main Toolbar",
        "tab.info": "Target Info",
        "tab.hex": "Hex Preview",
        "tab.flash": "Firmware",
        "tab.devices": "Devices",
        "tab.rtt": "RTT View",
        "tab.swo": "SWV",
        "hex.title": "Hex Preview",
        "hex.open": "Open File…",
        "hex.addr": "Address",
        "hex.size": "Size",
        "hex.read": "Read Chip",
        "hex.mem": "Device Memory",
        "hex.plus_tip": "Click + to open a file",
        "hex.read_by_size": "Read by Size",
        "hex.read_all": "Read All",
        "hex.save_as": "Save As…",
        "hex.fill": "Fill Memory",
        "hex.blank": "Blank Check",
        "hex.cmp_file": "Compare with File",
        "hex.cmp_two": "Compare Two Files",
        "status.connected": "Connected",
        "status.disconnected": "Disconnected",
        "status.connecting": "Connecting…",
        "status.failed": "Connect failed",
        "log.lang_switched": "UI language switched",
        "log.theme_dark": "Theme: dark",
        "log.theme_light": "Theme: light",
        "about.text": "ETools {ver}\nEmbedded MCU programming tool\nBackend: pyOCD\n\n{github}",
    },
}


def current_language() -> str:
    lang = (get_config().language or LANG_ZH).lower()
    return LANG_EN if lang.startswith("en") else LANG_ZH


def set_language(lang: str) -> None:
    lang = LANG_EN if str(lang).lower().startswith("en") else LANG_ZH
    cfg = get_config()
    if cfg.language != lang:
        cfg.language = lang
        save_config()


def tr(key: str, **kwargs) -> str:
    lang = current_language()
    table = _STRINGS.get(lang, _STRINGS[LANG_ZH])
    text = table.get(key) or _STRINGS[LANG_ZH].get(key) or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except Exception:
            return text
    return text
