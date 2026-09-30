# Changelog

本文件记录 ETools 的发布说明。发版前请在对应版本小节下写清 **新增 / 修复 / 改动**，再打 tag。

Release workflow 会读取与 tag 匹配的小节（如 \## [0.1.2]\ 或 \## [0.1.2] - 2026-09-13\）作为 GitHub Release 正文。

格式约定：

- 一级版本标题：\## [版本号] - YYYY-MM-DD\（日期可选）
- 分类：\### Added\ / \### Fixed\ / \### Changed\ / \### Removed- 未发布内容放在 \## [Unreleased]
---

## [0.5.0] - 2026-10-05

### Added

- **收发监视器**：关键字过滤高亮、方向过滤、RX/TX 流量统计、分帧合并、自动日志、CSV 导出、数据解释器（u8/u16/u32/f32）
- **编码** UTF-8 / GBK / Latin-1（发送与显示）；时间戳格式可选
- 串口：快捷指令 8 条（可导入导出）、发送文件、**Modbus 构造器**（RTU / TCP / ASCII）
- 网络：TCP Server **多客户端**、对端选择、快捷指令与历史、连通性检测、Modbus 构造器（默认 TCP）
- 终端：SSH **会话收藏**、常用命令、命令片段库、SFTP 删除；输出复制
- 烧录：最近固件列表、**批量烧录**、目标芯片可搜索
- 应用：**命令面板**（Ctrl+K）、设置中心（主题含跟随系统 / 语言 / 行为）、快捷键帮助、配置导入导出、窗口与左栏布局记忆
- Modbus：rame_rtu/tcp/ascii、LRC、按模式解析；功能码 01–06 / 0F / 10

### Changed

- 界面密度与 QSS 焦点、按钮语义统一（ui/kit.py）；监视器次要选项折叠为「更多」
- TCP Server 使用 select 并发 accept/recv

### Fixed

- QSplitter.setCollapsible 在子控件加入前调用导致的启动告警

---

## [0.4.0]

### Added

- **全局 Lua 脚本**（新工具页 \	ool-script\）：\etools.app/util/serial/net/term/flash\ 跨工具 API，支持数据处理、串口联调、自定义烧录流程；后台线程执行不卡 UI
- 串口**收包校验**：按当前校验算法核对 RX 帧尾，状态栏显示 OK/FAIL
- 串口**帧校验**：XOR / SUM8 / SUM16 / CRC-8 / CRC-16-MODBUS / CRC-16-CCITT / CRC-32，发送自动附加，实时预览校验值
- 串口**自动化脚本**：\send\ / \send_hex\ / \wait\ / \expect\ / \log\，不阻塞 UI 的逐步执行与超时中止
- Windows 安装包（Inno Setup / NSIS）安装与卸载后自动刷新 Explorer 图标缓存

### Changed

- 桌面品牌图标改为高对比亮蓝芯片+闪电，小尺寸可读；依赖新增 \lupa
---

## [0.3.0] - 2026-09-29

### Added

- **变量监控**（ELF 符号 + RTT/SWO 实时曲线）：`elf.py` 解析目标符号，`trace_stream.py` 解析 `EVM1` 帧协议，Program 页新增 Monitor 页签
- 变量数据流协议说明 `docs/variable_trace_protocol.md`；固件经 RTT 上行或 SWO ITM 推送采样，主机不再 SWD 轮询
- 串口助手：**快捷指令** 预填充文本框（5 条，持久化），一键发送
- 串口助手：**定时发送**（勾选参与轮询的指令 / 否则重复发送输入框，间隔 **1–600000 ms**）
- 串口：流控方式（无 / 软件 XON/XOFF / 硬件 RTS/CTS）、串口终端页、发送 BREAK
- 网络助手：接收格式 ASCII/HEX 切换；TCP Server 对端接入后才允许发送
- SFTP：取消传输、多文件下载到目录、逐文件进度

### Changed

- 左侧 rail 收起/展开按钮改为**图标栏底部 chevron**（与工具图标同一视觉语言），去掉顶部割裂感；收起后箭头纵向位置保持不变
- 工具页左侧参数栏支持手动拖宽（180–520），窗口缩放后仍记住宽度
- 流量监视器：保留收发记录并支持格式/时间戳切换后重绘；显示对端标签
- 依赖新增 `pyelftools`（ELF/DWARF 变量发现）

### Fixed

- 版本号单源：`pyproject.toml` 与 `etools.__version__` 均对齐 **0.3.0**

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
