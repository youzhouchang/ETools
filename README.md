# ETools (EmbeddedTools)

嵌入式工程师工作台：**MCU 烧录**（pyOCD / ST-Link / J-Link / DAP-Link）+ **串口 / 网络 / SSH 终端**工具，统一左侧工具栏切换。

**源码与发布：** [github.com/youzhouchang/ETools](https://github.com/youzhouchang/ETools)

- 仓库：https://github.com/youzhouchang/ETools  
- Releases：https://github.com/youzhouchang/ETools/releases  
- Issues / PR：https://github.com/youzhouchang/ETools/issues  

欢迎提 Issue 与 Pull Request。

## 功能

### 烧录工具（Program）

- 探针自动发现与连接（ST-Link / J-Link / CMSIS-DAP）
- 固件烧录（ELF / HEX / BIN / SREC），带实时进度条
- 芯片擦除（全片 / 按地址范围，均带二次确认）
- Flash 读取与回读校验
- 目标信息：UID / Flash / RAM / 电压 / Device ID
- 复位 / 挂起目标
- RTT / SWV 调试视图、Hex 预览（空白检查 / 文件比较 / 填充 RAM）

### 串口助手（Serial）

- pyserial 端口枚举与热插拔检测
- 收发监视（流式追加、HEX/文本、时间戳、暂停、自动滚动、保存日志）
- 常用波特率/校验配置 + DTR/RTS、行尾、发送格式（参数本地持久化）
- 发送历史（↑↓ 或历史按钮）

### 网络助手（Ethernet）

- TCP Client / TCP Server / UDP 收发（对端接入/断开提示）
- 本地端口与对端地址分离；监视器同串口（Hex/时间戳/保存）

### 终端工具（Terminal）

- SSH 命令执行（paramiko）；命令历史；可选私钥登录
- 主机密钥：未知主机弹窗确认信任，不匹配直接拒绝
- SFTP 上传 / 下载 / 上级目录 / 新建目录（host/user/port/路径持久化，密码不落盘）

## 日志策略

- **Program**：底部全局操作日志 + 进度条（烧录/连接/探针）
- **Serial / Ethernet**：页内收发监视，不占用全局日志
- **Terminal**：页内 SSH 输出 + 下方 SFTP 面板
- 窗口状态栏显示探针连接状态（跨工具共享）

## 环境要求

- Python 3.10+
- pyOCD、PySide6、pyserial、paramiko（见依赖）
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
| `ETools-portable-<ver>-linux-x86_64.tar.gz` | 便携包（内含 `install_desktop.sh` 可装桌面图标） |
| `ETools-<ver>-amd64.deb` | Debian/Ubuntu 安装包（多尺寸 hicolor 图标；包名 `etools`） |
| `ETools-<ver>-x86_64.AppImage` | AppImage（需 appimagetool；含 `.DirIcon`） |

便携包装桌面集成：

```bash
tar -xzf ETools-portable-*-linux-*.tar.gz
cd ETools
./install_desktop.sh   # 写入 ~/.local/share/{applications,icons}
```

系统依赖（Ubuntu）：

```bash
sudo apt-get install -y libusb-1.0-0 libgl1 libxkbcommon0 libdbus-1-3 libxcb-cursor0
# deb 打包
sudo apt-get install -y dpkg-dev
# AppImage（任选）
# 下载 appimagetool 到 tools/appimagetool 并 chmod +x
```

## 发布

打 Tag 即触发 GitHub Actions（`.github/workflows/release.yml`）：

1. 校验 Tag（`vX.Y.Z`）与 `etools/__init__.py` 中 `__version__` 一致  
2. 跑测试  
3. 在 Windows / Linux 上打包  
4. 创建 GitHub Release 并上传安装包  

```bash
# 1. 改版本号
# etools/__init__.py: __version__ = "0.2.0"

# 2. 提交并打 Tag
git add etools/__init__.py
git commit -m "Release v0.2.0"
git tag v0.2.0
git push origin main --tags
```

应用内：启动后自动检查一次；菜单 **帮助 → 检查更新…** 可手动检查（读取 GitHub Releases API）。发现新版本时，弹窗会以 Markdown 渲染更新说明，并支持**下载更新**；打包版（安装目录 / 便携包 / AppImage）下载完成后可**自动安装并重启**。源码运行时仅下载安装包，需手动升级。

仓库地址见文首；应用 **帮助 → 关于** 中也有 GitHub 链接入口。

## 架构

```
etools/
├── app.py              # 应用入口
├── config.py           # 配置管理（含 tools.* 偏好）
├── logger.py           # 日志
├── i18n.py             # 中英文案
├── core/               # 业务核心（无 UI 依赖）
│   ├── models.py       # 数据模型
│   ├── probe.py        # 探针抽象
│   ├── pyocd_driver.py # pyOCD 后端
│   ├── operations.py   # 烧录/擦除/读取/校验 门面
│   ├── serial_link.py  # 串口链路
│   ├── net_link.py     # TCP/UDP 链路
│   ├── ssh_link.py     # SSH/SFTP 链路
│   └── updater.py      # 应用更新
└── ui/                 # PySide6 界面
    ├── main_window.py  # 窗口编排（业务 + 状态栏）
    ├── shell.py        # 左侧工具 rail + 页栈 + 工具栏
    ├── runtime.py      # OpRunner / Worker（统一后台任务）
    ├── tool_prefs.py   # 工具参数持久化
    ├── styles.py       # QSS 主题
    ├── icons.py        # 主题感知图标
    ├── forms/          # Qt Designer 可编辑面板 .ui
    └── tools/
        ├── base.py         # ToolPage（左上下文 + 右工作区）
        ├── program_page.py # 烧录工作区
        ├── serial_page.py
        ├── ethernet_page.py
        ├── terminal_page.py
        └── sftp_panel.py
packaging/              # PyInstaller 打包
tests/                  # pytest 单元测试
docs/icons/             # 图标设计规范 + 生成脚本
```

所有工具页共用 `ToolPage` 布局语言；后台任务统一走 `etools.ui.runtime.OpRunner`。
工具页通过 `toolbar_actions()` 向 `ToolShell` 暴露公开动作，不再依赖私有 `_on_*`。

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
