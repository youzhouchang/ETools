# Changelog

本文件记录 ETools 的发布说明。发版前请在对应版本小节下写清 **新增 / 修复 / 改动**，再打 tag。

Release workflow 会读取与 tag 匹配的小节（如 \## [0.1.2]\ 或 \## [0.1.2] - 2026-09-13\）作为 GitHub Release 正文。

格式约定：

- 一级版本标题：`## [版本号] - YYYY-MM-DD`（日期可选）
- 分类：`### Added` / `### Fixed` / `### Changed` / `### Removed`
- 未发布内容放在 `## [Unreleased]`

## [Unreleased]

### Added

- 烧录页新增「烧录工具」页签：
  - 选项字节：读写 STM32 F0/F1/F3/F4/G0/G4/L4/H7 的选项字节，包括 RDP 读保护 Level 0/1、写保护、BOR、看门狗、启动地址。支持恢复出厂值，危险字段带标记并需二次确认。不提供 RDP Level 2。
  - 量产烧录：一键完成擦除（扇区 / 整片）、烧录、校验、读保护和运行。支持多种格式的序列号自增写入、96 位 UID 写入、CSV 量产日志和通过 / 失败统计。
  - 镜像工具：合并多个 HEX / BIN / SREC / ELF 并检测冲突；支持重定位、删除或保留区间、填充空隙、末尾对齐、改写字节、CRC32 / SHA256 和撤销；可导出 HEX / SREC / BIN，或直接作为烧录固件。
  - 串口 Bootloader：按 STM32 AN3155 协议烧录、读取、整片擦除，开启或解除读保护，解除写保护；可用 DTR / RTS 自动进入 Bootloader。
- 增量烧录：只擦写内容有变化的扇区。
- 外部 Flash：挂载 CMSIS `.FLM` 下载算法后，可烧录、擦除和校验 QSPI / SPI 等外部存储，每次连接自动挂载。

### Fixed

- 串口 Bootloader：读取任意地址/长度时按 AN3155 要求做 4 字节对齐（起始地址非 4 的倍数时此前会被芯片 NACK）。
- 镜像工具 / 量产烧录：CRC32、SHA256 改成只对各段真实数据计算，不再把整个地址区间（含中间空隙）拼成一整块；片内 Flash 与外部 QSPI Flash 等跨度很大的镜像不会再因为超限而计算失败。
- 镜像工具导出 SREC：S7 结束记录的地址改为镜像起始地址，不再固定写 0x00000000。
- 选项字节：STM32F4 的 BOR 阈值文字由 2.2/2.5/2.8 V 改为参考手册更准确的 2.1/2.4/2.7 V。

### Changed

## [0.7.0] - 2026-10-29

### Added

- 仪表盘：网格拖放布局（拖标题移动、拖右下角缩放、右键删除），新增「指示灯」控件；三维姿态控件支持固定翼 / 四旋翼 / 方块 / 地平仪，输入欧拉角或四元数。
- Lua 二次处理仪表盘与地图数据：`etools.frames.recv / wait / latest / publish`（结果以数据源 `lua` 发布）、`etools.dash.*`、`etools.map.*`；仪表盘和地图数据源新增「Lua 脚本」；新增示例「9_仪表盘与地图二次处理」。
- 地图底图可选高德路网（自动 WGS84→GCJ-02）、Esri 街道、OpenStreetMap 或无底图，轨迹颜色可选。
- 烧录页新增诊断：HardFault 寄存器解码与 RTOS 线程快照。
- 应用内使用教程（帮助 → 使用教程，内容来自 `docs/guide.md`）。
- Qt 内部警告转成可读的日志与状态栏提示。

### Fixed

- YMODEM/XMODEM：接收端按头包大小去掉末尾填充（含空文件，兼容 `size mtime mode` 头格式）；重复包与重传头包只确认不追加；校验和模式的握手与首块请求符合标准。
- 串口：不支持 DTR/RTS 的端口（pty、部分蓝牙 / 虚拟串口）可以正常打开，打开失败时释放端口。
- 串口、CAN、网络连接与端口扫描移到后台线程，不再卡住界面；RTT 轮询改为独立线程，重启会话时旧线程不再干扰新会话。
- SSH 单次命令同时读取 stdout 与 stderr，避免大量 stderr 输出导致卡死，每路输出上限 4 MiB。
- 内置 CANopen 示例对 `can.recv` 结果使用 `ipairs` 时报错。
- 收发记录满 5000 条后每次刷新都全量重绘；过滤高亮优先标出最新匹配。
- 关闭窗口时统一停止定时器、自动日志与后台任务。
- 部分界面文字未跟随语言切换。

### Changed

- 安全：Lua 脚本无法调用 Python 对象，`load` 只接受文本代码；自动更新按 Release 公布的 SHA-256 校验下载文件；SSH 首次连接必须确认主机指纹。
- 配置：原子写入；损坏的配置文件改名备份后提示；导入时拒绝格式或类型错误的文件且不改动当前设置。
- 日志按 5 MiB 轮转，保留 3 份。
- CI 增加 Python 3.10；发布时同时校验 `pyproject.toml` 与 `etools/__init__.py` 的版本号。

## [0.6.1] - 2026-10-17

### Added

- 串口自动重连（端口丢失/链路错误后指数退避重开，可开关并持久化）。
- 连接中可修改波特率/数据位/校验/停止位/流控（防抖后安全重开）。
- 触发发送：最多 8 条文本/HEX/正则匹配规则，支持冷却与“仅一次”。
- 快捷指令 `Alt+1…8` 发送（可开关；避开工具切换用的 `Ctrl+1…5`）。
- 曲线解析扩展：`key=value` 行与 HEX 结构模板；视图支持时域 / 频域 FFT / 柱状。

### Fixed

- 冻结包保留 pyOCD 探针入口，并在入口失效时直接扫描 ST-Link、CMSIS-DAP、J-Link 和 Picoprobe。
- 烧录校验前复位并丢弃内存缓存，避免把旧 Flash 内容当成校验失败。
- 擦除、烧录、读取、校验和填充结束后给出完成或失败提示；擦除后刷新内存信息。
- Hex 预览页签与标题对齐，同一固件只打开一个页签，并烧录当前打开的固件。
- 升级按当前安装包类型替换：AppImage、deb、便携包各自对应，不再按固定下载顺序。

### Changed

- 串口/网络曲线与 `FrameHub` 共用同一解析结果，避免双缓冲不同步。

## [0.6.0] - 2026-10-11

### Added

- MQTT 3.1.1 QoS 0 客户端，支持发布、订阅、连接状态和密码不落盘。
- 地图页支持帧序号或 JSON 键绑定经纬度、轨迹、缩放、平移和可选 OSM 底图。
- Serial Studio 风格仪表盘：数值、仪表、条、单曲线和多曲线控件，字段列表切换及 JSON 工程。
- 串口、网络和 MQTT 共用 `/*1,2*/` / 数值 JSON 帧流；串口和网络增加快速曲线。
- CAN DBC 加载与实时信号解码，Lua SDO 读返回 expedited 响应值。
- SSH 交互式 PTY 会话、终端收发 Lua API；网络 Lua API 增加连接状态和等待应答。
- 项目配置、烧录联调流程、原始采集 JSON 回放、工具状态标记和脚本删除恢复。

### Fixed

- pyOCD 操作在 UI 与 Lua 之间串行化，长时间烧录不再阻塞界面线程。
- 无目标芯片响应时给出独立状态；网络、SSH 与 MQTT 连接移至后台。
- 暂停监视器仍保留记录；更多操作区不再挤压日志框，导出改为可直接预览的文本。
- 拒绝帧和仪表盘工程中的非有限数值，避免地图或曲线绘制异常。
- DBC 保留标准/扩展帧类型并校验 DLC，避免同号帧碰撞和截断解码。
- MQTT 保活按客户端发送时间计算；地图瓦片限制并发、失败退避并在退出时取消。
- SSH 新主机密钥钉扎到用户确认的指纹，SFTP 与交互通道串行访问传输层。

### Changed

- 烧录后端统一为 pyOCD；主题、语言、工具名称及串口过滤选项集中到设置对话框。
- 串口与网络发送区重新排布，连接参数和高级串口参数保持直接可见。

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
