# ETools (EmbeddedTools)

嵌入式 MCU 烧录工具，基于 **pyOCD**，支持 ST-Link / J-Link / DAP-Link，可对 Cortex-M 系列 MCU 进行固件烧录、读取、擦除与校验。

## 功能

- 探针自动发现与连接（ST-Link / J-Link / CMSIS-DAP）
- 固件烧录（ELF / HEX / BIN / SREC），带实时进度条
- 芯片擦除 / 扇区擦除
- Flash 读取与回读校验
- 目标信息：UID / Flash / RAM / 电压 / Device ID
- 复位 / 挂起目标

## 环境要求

- Python 3.10+
- pyOCD、PySide6（见依赖）
- 对应探针驱动（ST-Link / J-Link / CMSIS-DAP）

## 安装

```powershell
pip install -e ".[dev]"
```

## 运行

```powershell
python -m etools
```

## 测试

```powershell
pytest
```

## 打包

### Windows（`.bat`，无需执行策略）

```bat
cd /d D:\Code\ETools
packaging\package_windows.bat
:: 可选
packaging\package_windows.bat --clean
packaging\package_windows.bat --portable-only
packaging\package_windows.bat --no-installer
```

产物（`dist\release\`）：

| 文件 | 说明 |
|------|------|
| `ETools-portable-<ver>-win64.zip` | 便携包，解压即用 |
| `ETools-setup-<ver>-win64.exe` | 安装包（需 Inno Setup 或 NSIS） |
| `dist\ETools\ETools.exe` | PyInstaller onedir 原始目录 |

安装包依赖任选其一：

- [Inno Setup 6](https://jrsoftware.org/isdl.php)（推荐，脚本 `packaging/etools.iss`）
- [NSIS](https://nsis.sourceforge.io/Download)（脚本 `packaging/etools.nsi`）

未安装编译器时会跳过安装包，便携包仍会生成。

### Ubuntu / Linux

```bash
bash packaging/package_linux.sh
# 可选
bash packaging/package_linux.sh --clean
bash packaging/package_linux.sh --portable-only
bash packaging/package_linux.sh --skip-appimage
```

产物（`dist/release/`）：

| 文件 | 说明 |
|------|------|
| `ETools-portable-<ver>-linux-x86_64.tar.gz` | 便携包 |
| `etools_<ver>_amd64.deb` | Debian/Ubuntu 安装包 |
| `ETools-<ver>-x86_64.AppImage` | AppImage（需 appimagetool） |

系统依赖（Ubuntu）：

```bash
sudo apt-get install -y libusb-1.0-0 libgl1 libxkbcommon0 libdbus-1-3 libxcb-cursor0
# deb 打包
sudo apt-get install -y dpkg-dev
# AppImage（任选）
# 下载 appimagetool 到 tools/appimagetool 并 chmod +x
```

## 架构

```
etools/
├── app.py              # 应用入口
├── config.py           # 配置管理
├── logger.py           # 日志
├── core/               # 业务核心（无 UI 依赖）
│   ├── models.py       # 数据模型 / ProgressInfo / TargetDetails
│   ├── probe.py        # 探针抽象
│   ├── pyocd_driver.py # pyOCD 后端
│   └── operations.py   # 烧录/擦除/读取/校验 门面
└── ui/                 # PySide6 界面
    ├── main_window.py  # 线程安全进度 + 主窗口
    ├── styles.py       # QSS 主题
    ├── ui_loader.py    # 加载 Qt Designer .ui
    ├── forms/          # Qt Designer 可编辑界面
    │   ├── main_window.ui
    │   ├── probe_panel.ui
    │   ├── flash_panel.ui
    │   ├── target_info_panel.ui
    │   └── log_panel.ui
    └── widgets/
        ├── probe_panel.py
        ├── flash_panel.py
        ├── target_info_panel.py
        └── log_panel.py
packaging/              # PyInstaller 打包
tests/                  # pytest 单元测试
```

## Qt Designer

界面布局在 `etools/ui/forms/*.ui`，可直接用 **Qt Designer** 打开编辑：

```powershell
# Windows（若已安装 Qt）
designer etools\ui\forms\main_window.ui
```

Python 侧通过 `etools.ui.ui_loader.load_form` / `embed_form` 加载，
控件用 `objectName` 查找（如 `probeCombo`、`programBtn`）。
改完 `.ui` 后无需改布局代码，只要 objectName 保持一致即可。

## 探针支持

通过 pyOCD 原生探针插件：

| 探针 | pyOCD 类型 | 说明 |
|------|------------|------|
| ST-Link V2 / V2-1 / V3 | `stlink` | 原生 USB，支持目标电压读取 |
| SEGGER J-Link | `jlink` | 依赖 pylink-square |
| DAP-Link / CMSIS-DAP | `cmsisdap` | 一等公民，最稳 |

## 目标芯片

使用 pyOCD 内置 target 名称（如 `stm32f103rc`、`nrf52840`、`rp2040`），
也可通过 CMSIS-Pack 扩展更多型号。
