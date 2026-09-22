# Changelog

本文件记录 ETools 的发布说明。发版前请在对应版本小节下写清 **新增 / 修复 / 改动**，再打 tag。

Release workflow 会读取与 tag 匹配的小节（如 `## [0.1.2]` 或 `## [0.1.2] - 2026-09-13`）作为 GitHub Release 正文。

格式约定：

- 一级版本标题：`## [版本号] - YYYY-MM-DD`（日期可选）
- 分类：`### Added` / `### Fixed` / `### Changed` / `### Removed`
- 未发布内容放在 `## [Unreleased]`

---

## [0.2.0] - 2026-09-22

### Added

- 多工具壳层 `etools/ui/shell.py`：左侧 icon rail + 页栈 + 各工具公开 toolbar
- 专用 rail 图标 `tool-program` / `tool-serial` / `tool-ethernet` / `tool-terminal`
- 工具参数持久化：串口/网络/SSH host·user·port·key·SFTP 路径写入 `config.extra["tools"]`（密码不落盘）
- `ToolPage.toolbar_actions()` 公开动作 API；`etools/ui/runtime.py` 统一 `OpRunner`
- `ProgramPage`：烧录工作区对齐 ToolPage 壳层语言（左探针 + 右 tabs + 底部日志/进度）
- 串口助手：pyserial 列端口 / 打开关闭 / 收发；下拉展开刷新 + 2s 热插拔检测
- 网络助手：TCP Client/Server 与 UDP 收发
- 终端：SSH 命令 + SFTP 传输；工具页中英文案与语言切换
- 左侧时钟频率默认 **10000 kHz**（SpinBox）
- **共享流量监视器** `traffic_view.py`：流式追加、HEX/文本、时间戳、暂停、自动滚动、保存日志
- 串口：行尾（LF/CR/CRLF）、HEX 发送、发送历史、DTR/RTS
- 网络：UDP 本地端口与对端分离、TCP Server 对端接入/断开提示、默认端口 8080
- 终端：命令历史（↑↓）、私钥登录、清屏
- SFTP：挂载在 Terminal 页下方（可见文件列表）、上级目录、新建目录、双击下载、成功/失败状态栏
- SSH 主机密钥：未知主机指纹确认后信任写入 known_hosts；不匹配拒绝连接
- 范围擦除（按地址/长度，扇区对齐）+ 全片/范围擦除二次确认
- 全量 i18n：探针/固件/Hex/RTT/SWV/监视器等硬编码中文迁入 `i18n.py`

### Fixed

- 版本号单源：`pyproject.toml` 与 `etools.__version__` 均对齐 **0.2.0**
- 左侧 rail 不再借用 devices/probe/rtt 图标，语义可扫视
- rail 高度按工具数量计算，不再硬编码 4 个按钮
- 工具栏绑定改为公开 API，避免 `page._on_*` 私有方法外泄
- **SFTP 面板创建后未挂入布局**（此前不可见）— 已嵌入 Terminal 页
- 串口/网络清屏工具栏文案误用「收发监视」
- 语言切换时 Program 子面板（Hex/RTT/SWV/目标信息）不刷新
- ruff：E501 / B007 / F401 / E402 / I001
- `.gitignore` 根级 `tools/` 误忽略 `etools/ui/tools/`，导致打包后缺失四页源码（CI `ModuleNotFoundError`）

### Changed

- 产品定位文案：MCU 烧录工具 → **嵌入式工程师工作台**（烧录 + 串口/网络/SSH）
- README 架构图补全 `ui/tools`、`core/*_link`、图标体系与日志策略
- 左侧工具栏为 **纯图标 + tooltip**（非旋转文字）；CHANGELOG 与实现对齐
- 后台任务模型收敛为 `OpRunner`（Program / Terminal / SFTP 共用）
- 日志策略：全局日志仅在 Program；Serial/Net/Terminal 使用页内视图

---

## [0.1.3] - 2026-09-13

### Added

- Release 说明 Markdown 表格渲染（Downloads 表不再乱版）

### Fixed

- 打包版点击更新后静默下载并安装，不再弹出「保存安装包」与二次确认

### Changed

---

## [0.1.2] - 2026-09-13

### Added

- `CHANGELOG.md` 作为发版说明来源；GitHub Release 正文自动读取对应版本小节
- Release 说明包含 Assets 表与 SHA-256 校验和代码块

### Fixed

- Ubuntu 桌面 / 开始菜单 / 任务栏图标：`StartupWMClass`、`desktopFileName`、`Icon` 统一为 `etools`；窗口图标优先 `QIcon.fromTheme`，并打包 PNG 回退
- deb 安装后更完整地刷新 hicolor / desktop database

### Changed

- PyInstaller 附带预渲染 PNG logo，降低 SVG 渲染失败导致默认图标的风险

---

## [0.1.1] - 2026-09-13

### Added

- 应用内更新：Markdown 渲染发布说明、直接下载、打包版可自动安装并重启
- 连接目标后自动加载 Flash 首页到 Hex 预览（对齐 CubeProgrammer）
- Hex 预览「填充内存」：仅支持 RAM，带字节输入与二次确认

### Fixed

- Linux CI AppImage 打包：完整提取 appimagetool AppDir，修复 `AppRun` 相对路径导致的 127 失败
- 日志区随窗口高度自适应，不再被上方内容压扁
- 固件操作页 Flash 读取行：地址/长度标签与控件贴合，不再被撑开

### Changed

- 主窗口默认高度 820，进度条与日志同属底部分栏（进度条在上）
- 固件操作区控件高度收紧，去掉「固件文件」「Flash 读取」冗余标签
- Release 产物统一 `ETools` 前缀（deb 为 `ETools-<ver>-amd64.deb`，包名仍为 `etools`）
- Hex「读取全部」优先使用目标实际 Flash 容量

---

## [0.1.0] - 2026-09-12

### Added

- 首个公开发布：探针扫描/连接、烧录/擦除/校验/复位、Hex 预览、目标信息、设备管理
- RTT View / SWV 页面
- Windows portable / setup 与 Linux portable / deb / AppImage 打包流水线
