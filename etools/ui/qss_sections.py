"""Stylesheet fragments, joined by build_stylesheet."""
GLOBAL_QSS = '''/* ========== Global — compact ========== */
* {{
    font-size: 12px;
}}
QWidget {{
    background: {bg};
    color: {text};
    font-family: "Segoe UI", "Microsoft YaHei UI", "PingFang SC", sans-serif;
    font-size: 12px;
}}
QMainWindow, QDialog {{
    background: {bg};
}}
QToolTip {{
    background: {bg_panel};
    color: {text};
    border: 1px solid {border};
    padding: 3px 6px;
    font-size: 11px;
}}
QTabWidget::pane {{
    border: 1px solid {border};
    border-radius: 6px;
    background: {bg};
    top: -1px;
}}
QTabBar::tab {{
    background: {bg_input};
    color: {text_dim};
    border: 1px solid {border};
    border-bottom: none;
    border-top-left-radius: 5px;
    border-top-right-radius: 5px;
    padding: 4px 12px;
    margin-right: 1px;
    min-width: 64px;
    max-height: 24px;
    font-size: 12px;
}}
QTabBar::tab:selected {{
    background: {bg};
    color: {text};
    border-color: {accent};
}}
QTabBar::tab:hover:!selected {{
    color: {text};
    background: {bg_hover};
}}
/* Hex document sub-tabs — extra compact */
QTabWidget#hexTabs QTabBar::tab {{
    padding: 1px 8px;
    min-width: 40px;
    max-height: 18px;
    font-size: 11px;
    margin-right: 0px;
}}
QTabWidget#hexTabs QTabBar {{
    icon-size: 12px;
}}
QTabWidget#hexTabs::pane {{
    top: -1px;
    margin-top: 1px;
}}

'''
PANELS_QSS = '''/* ========== Panels ========== */
QFrame#panel {{
    background: {bg};
    border: 1px solid {border};
    border-radius: 6px;
}}
QLabel#panelTitle {{
    color: {text};
    font-size: 13px;
    font-weight: 600;
}}
QLabel#hint {{
    color: {text_dim};
    font-size: 11px;
}}
QLabel#infoValue {{
    color: {text};
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 11px;
}}
QLabel#progressLabel {{
    color: {text_dim};
    font-size: 11px;
}}
QLabel#statusOk {{ color: {success}; font-weight: 600; font-size: 11px; }}
QLabel#statusErr {{ color: {danger}; font-weight: 600; font-size: 11px; }}
QLabel#statusWarn {{ color: {warning}; font-weight: 600; font-size: 11px; }}
QLabel#brandTitle {{
    color: {text};
    font-size: 18px;
    font-weight: 700;
    min-height: 22px;
}}

'''
CONTROLS_QSS = '''/* ========== Controls — compact ========== */
QPushButton {{
    background: {bg_input};
    color: {text};
    border: 1px solid {border};
    border-radius: 5px;
    padding: 5px 12px;
    min-height: 18px;
    font-size: 12px;
}}
QPushButton:hover {{
    background: {bg_hover};
    border-color: {accent};
}}
QPushButton:pressed {{ background: {bg_panel}; }}
QPushButton:disabled {{
    color: {text_muted};
    background: {bg_panel};
    border-color: {border};
}}
QPushButton#accent {{
    background: {accent};
    color: {on_accent};
    border: none;
    font-weight: 600;
    padding: 7px 14px;
}}
QPushButton#accent:hover {{ background: {accent_hover}; }}
QPushButton#accent:disabled {{
    background: {bg_input};
    color: {text_muted};
}}
QToolButton#accentTool {{
    background: {accent};
    color: {on_accent};
    border: none;
    border-radius: 5px;
    padding: 5px 10px;
    font-weight: 600;
    font-size: 12px;
}}
QToolButton#accentTool:hover {{ background: {accent_hover}; }}
QToolButton#accentTool:disabled {{
    background: {bg_input};
    color: {text_muted};
}}
QToolButton#accentTool::menu-button {{
    border-left: 1px solid rgba(0,0,0,0.2);
    width: 14px;
}}
QPushButton#danger {{
    background: transparent;
    color: {danger};
    border: 1px solid {danger};
    padding: 7px 14px;
}}
QPushButton#danger:hover {{ background: rgba(255, 92, 92, 0.12); }}
QPushButton#ghost {{
    background: transparent;
    border: 1px solid {border};
    color: {text_dim};
    padding: 4px 8px;
}}
QPushButton#ghost:hover {{
    color: {text};
    border-color: {accent};
}}
QToolButton#keyBrowse {{
    border: none;
    background: transparent;
    padding: 0 6px;
    color: {text_dim};
    font-size: 11px;
}}
QToolButton#keyBrowse:hover {{
    color: {text};
    background: {bg_input};
    border-radius: 4px;
}}

QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox, QPlainTextEdit {{
    background: {bg_input};
    color: {text};
    border: 1px solid {border};
    border-radius: 5px;
    padding: 4px 8px;
    selection-background-color: {accent};
    selection-color: {on_accent};
    font-size: 12px;
}}
QComboBox:hover, QLineEdit:hover, QSpinBox:hover {{
    border-color: {accent};
}}
QComboBox {{
    padding-right: 26px;
    min-width: 0;
}}
QComboBox::drop-down {{
    subcontrol-origin: border;
    subcontrol-position: center right;
    border: none;
    background: transparent;
    width: 22px;
}}
QComboBox::down-arrow {{
    image: url({arrow_url});
    width: 10px;
    height: 10px;
}}
QSpinBox, QDoubleSpinBox {{
    padding-right: 30px;
}}
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 22px;
    border: none;
    border-left: 1px solid {border};
    border-bottom: 1px solid {border};
    border-top-right-radius: 5px;
    background: {bg_hover};
    margin: 1px 1px 0 0;
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 22px;
    border: none;
    border-left: 1px solid {border};
    border-bottom-right-radius: 5px;
    background: {bg_hover};
    margin: 0 1px 1px 0;
}}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
    background: {accent};
    border-left-color: {accent};
}}
QSpinBox::up-button:pressed, QDoubleSpinBox::up-button:pressed,
QSpinBox::down-button:pressed, QDoubleSpinBox::down-button:pressed {{
    background: {accent_hover};
}}
QSpinBox::up-button:disabled, QSpinBox::down-button:disabled,
QDoubleSpinBox::up-button:disabled, QDoubleSpinBox::down-button:disabled {{
    background: {bg_input};
    border-left-color: {border};
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    image: url({spin_up_url});
    width: 9px;
    height: 9px;
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    image: url({spin_down_url});
    width: 9px;
    height: 9px;
}}
QSpinBox::up-arrow:disabled, QSpinBox::down-arrow:disabled {{
    opacity: 0.35;
}}
QComboBox QAbstractItemView,
QListView {{
    background-color: {bg_panel};
    color: {text};
    border: 1px solid {border};
    border-radius: 6px;
    padding: 6px;
    outline: none;
    selection-background-color: {accent};
    selection-color: {on_accent};
    font-size: 12px;
}}
QComboBox QAbstractItemView::item,
QListView::item {{
    background-color: {bg_panel};
    color: {text};
    min-height: 24px;
    padding: 3px 6px;
    border-radius: 4px;
    margin: 1px 2px;
}}
QComboBox QAbstractItemView::item:selected,
QListView::item:selected {{
    background-color: {accent};
    color: {on_accent};
}}
QComboBox QAbstractScrollArea {{
    background: transparent;
    border: none;
}}

QCheckBox {{
    spacing: 6px;
    color: {text_dim};
    font-size: 12px;
}}
QCheckBox::indicator {{
    width: 14px;
    height: 14px;
    border-radius: 3px;
    border: 1px solid {border};
    background: {bg_input};
}}
QCheckBox::indicator:checked {{
    background: {accent};
    border-color: {accent};
}}

QProgressBar {{
    background: {bg_input};
    border: 1px solid {border};
    border-radius: 3px;
    text-align: center;
    color: {text};
    height: 8px;
    max-height: 10px;
}}
QProgressBar::chunk {{
    background: {accent};
    border-radius: 2px;
}}

QPlainTextEdit#logView {{
    background: {log_bg};
    color: {text_dim};
    border: 1px solid {border};
    border-radius: 6px;
    font-family: "Cascadia Code", "Consolas", "JetBrains Mono", monospace;
    font-size: 11px;
    padding: 6px;
}}

QTextBrowser, QTextEdit {{
    background: {bg_input};
    color: {text};
    border: 1px solid {border};
    border-radius: 6px;
    padding: 6px 8px;
    selection-background-color: {accent};
    selection-color: {on_accent};
    font-size: 12px;
}}
QTextBrowser a, QTextEdit a {{ color: {accent}; }}

QMessageBox {{
    background: {bg};
    color: {text};
}}
QMessageBox QLabel {{
    color: {text};
    background: transparent;
}}
QProgressDialog {{
    background: {bg};
    color: {text};
}}
QProgressDialog QLabel {{
    color: {text};
    background: transparent;
}}

'''
SCROLL_QSS = '''/* ========== Scroll ========== */
QScrollArea {{
    border: none;
    background: transparent;
}}
QScrollArea QWidget#qt_scrollarea_viewport {{
    background: transparent;
}}
QScrollBar:vertical {{
    background: {bg};
    width: 8px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {border};
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{ background: {accent}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{
    background: {bg};
    height: 0;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

'''
CHROME_QSS = '''/* ========== Chrome ========== */
QMenuBar {{
    background: {bg};
    color: {text};
    border-bottom: 1px solid {border};
    padding: 2px 6px;
    font-size: 12px;
}}
QMenuBar::item:selected {{
    background: {bg_hover};
    border-radius: 4px;
}}
QMenu {{
    background: {bg_panel};
    color: {text};
    border: 1px solid {border};
    border-radius: 6px;
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 24px 6px 12px;
    border-radius: 4px;
}}
QMenu::item:selected {{
    background: {accent};
    color: {on_accent};
}}
QToolBar {{
    background: {bg};
    border: none;
    border-bottom: 1px solid {border};
    spacing: 6px;
    padding: 4px 8px;
}}
QToolButton {{
    background: transparent;
    color: {text_dim};
    border: 1px solid transparent;
    border-radius: 5px;
    padding: 4px 8px;
}}
QToolButton:hover {{
    color: {text};
    background: {bg_hover};
    border-color: {border};
}}
QWidget#toolRail,
QWidget#toolRailBox {{
    background: {bg_panel};
    border: 1px solid {border};
    border-radius: 8px;
}}
QWidget#toolRailBox {{
    border-right: none;
    border-top-right-radius: 0;
    border-bottom-right-radius: 0;
}}
QToolButton#toolRailBtn {{
    background: transparent;
    border: none;
    border-radius: 8px;
}}
QToolButton#railCollapseBtn {{
    background: transparent;
    border: none;
    border-radius: 8px;
    padding: 0;
}}
QToolButton#railCollapseBtn:hover {{
    background: transparent;
    border: none;
}}
QGroupBox#ctxGroup,
QGroupBox#mainGroup {{
    background: {bg_panel};
    border: 1px solid {border};
    border-radius: 8px;
    margin-top: 14px;
    padding-top: 6px;
    font-size: 12px;
    font-weight: 600;
    color: {text};
}}
QGroupBox#ctxGroup::title,
QGroupBox#mainGroup::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    top: 2px;
    padding: 0 4px;
}}
QGroupBox#mainGroup:unchecked {{
    border: none;
    border-top: 1px solid {border};
    border-radius: 0;
    margin-top: 0;
    padding: 2px 0 0 0;
    background: transparent;
}}
QGroupBox#mainGroup:unchecked::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 0;
    top: 0;
    padding: 6px 2px 4px 0;
    color: {text_muted};
    font-weight: 500;
}}
QGroupBox#mainGroup::indicator {{
    width: 14px;
    height: 14px;
}}
QGroupBox#mainGroup:checked {{
    background: {bg_panel};
    border: 1px solid {border};
    border-radius: 8px;
    margin-top: 24px;
    padding: 16px 8px 8px 8px;
}}
QGroupBox#mainGroup:checked::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 8px;
    top: 4px;
    padding: 0 6px;
    background: transparent;
}}
QGroupBox#mainGroup::indicator:unchecked,
QGroupBox#mainGroup::indicator:checked {{
    width: 14px;
    height: 14px;
}}
QLineEdit {{
    background: {bg_input};
    color: {text};
    border: 1px solid {border};
    border-radius: 5px;
    padding: 4px 8px;
    selection-background-color: {accent};
    selection-color: {on_accent};
    font-size: 12px;
}}
QLineEdit:hover,
QLineEdit:focus {{
    border-color: {accent};
}}
QLineEdit[ipInvalid="true"] {{
    border-color: {danger};
}}
QLineEdit:disabled {{
    color: {text_muted};
    background: {bg_panel};
}}
QStatusBar {{
    background: {bg};
    color: {text_dim};
    border-top: 1px solid {border};
    font-size: 11px;
}}
QStatusBar QLabel {{
    background: transparent;
    padding: 0 4px;
}}
QLabel#statsLabel {{
    color: {text_dim};
    font-size: 11px;
    font-family: "Cascadia Mono", "Consolas", monospace;
}}
QWidget#trafficBadge {{
    background: transparent;
}}
QLabel#trafficBadgeText {{
    background: transparent;
    color: {text_dim};
    font-size: 11px;
    font-family: "Cascadia Mono", "Consolas", monospace;
    padding: 0 2px 0 4px;
}}
QPushButton#trafficBadgeClear {{
    background: transparent;
    border: none;
    border-radius: 3px;
    color: {text_muted};
    font-size: 11px;
    padding: 0 6px 0 2px;
}}
QPushButton#trafficBadgeClear:hover {{
    color: {accent};
    background: {bg_hover};
}}
QPushButton#trafficBadgeClear:pressed {{
    color: {on_accent};
    background: {accent};
}}
QLabel#mutedLabel {{
    color: {text_muted};
    font-size: 11px;
}}
QLabel#statusTask {{
    color: {text_dim};
    font-size: 11px;
}}
/* Focus ring — one accent outline for keyboard users */
QLineEdit:focus,
QPlainTextEdit:focus,
QComboBox:focus,
QSpinBox:focus {{
    border: 1px solid {accent};
}}
QPushButton:focus {{
    border: 1px solid {accent};
}}
/* Command palette */
QDialog#CommandPalette {{
    background: {bg_panel};
    border: 1px solid {border};
    border-radius: 10px;
}}
QLineEdit#paletteInput {{
    background: {bg_input};
    border: 1px solid {border};
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 14px;
    selection-background-color: {accent};
    selection-color: {on_accent};
}}
QLineEdit#paletteInput:focus {{
    border-color: {accent};
}}
QListWidget#paletteList {{
    background: {bg};
    border: 1px solid {border};
    border-radius: 8px;
    outline: none;
    font-size: 13px;
    padding: 4px;
}}
QListWidget#paletteList::item {{
    min-height: 32px;
    padding: 6px 10px;
    border-radius: 6px;
    margin: 2px 4px;
}}
QListWidget#paletteList::item:selected {{
    background: {accent};
    color: {on_accent};
}}
QListWidget#paletteList::item:hover:!selected {{
    background: {bg_hover};
}}
QLabel#toolBadge {{
    color: {accent};
    font-size: 11px;
    font-weight: 600;
    padding: 0 8px;
}}
QCheckBox {{
    spacing: 6px;
    color: {text_dim};
    font-size: 12px;
}}
QCheckBox::indicator {{
    width: 14px;
    height: 14px;
    border: 1px solid {border};
    border-radius: 3px;
    background: {bg_input};
}}
QCheckBox::indicator:checked {{
    background: {accent};
    border-color: {accent};
}}
QCheckBox::indicator:hover {{
    border-color: {accent};
}}
'''
SECTIONS = (
    GLOBAL_QSS,
    PANELS_QSS,
    CONTROLS_QSS,
    SCROLL_QSS,
    CHROME_QSS,
)
