# ETools 图标体系设计

## 产品定位

ETools 是面向嵌入式工程师的 **MCU 烧录 / 调试桌面工具**（ST-Link / J-Link / DAP-Link）。  
图标需传达：**芯片、烧录、连接、精确、可靠** —— 工业工具感，而非消费级 App。

## 风格锚点

参考 **STM32CubeProgrammer / SEGGER Embedded Studio** 的语义清晰度，视觉上对齐 **Feather / Lucide** 的克制几何：

- 24×24 网格，视觉安全区 20×20（四周 2px 留白）
- 线性描边为主，关键动作可有局部强调填充（烧录闪电、停止块）
- 圆角端点 / 圆角连接（`stroke-linecap="round"`）
- 禁止渐变滥用、禁止拟物阴影（应用 Logo 图标除外）

## 色板

| 角色 | Dark | Light | 用途 |
|------|------|-------|------|
| Accent | `#3B9EFF` | `#1A73E8` | 主操作、激活态、Logo 主色 |
| Text | `#E6EAF0` | `#1F2933` | 默认描边（UI 内优先 `currentColor`） |
| Text Dim | `#9AA3B2` | `#5B6B7C` | 次要 / 工具栏图标 |
| Success | `#3DDC97` | `#0F9D6E` | 校验通过、连接成功 |
| Warning | `#F5A623` | `#C27803` | 警告 |
| Danger | `#FF5C5C` | `#D93025` | 擦除、错误、断开 |
| BG | `#1E222A` | `#F3F5F8` | 面板底色 |
| Logo BG | `#0B1220` → `#1A2740` | 同左 | 应用图标底 |

**原则**：功能图标默认 `stroke="currentColor"`，由 `etools/ui/icons.py` 按主题注入前景色；语义色仅用于状态徽章与强调按钮。

## 网格与几何

```
viewBox = "0 0 24 24"
stroke-width = 1.75
stroke-linecap = round
stroke-linejoin = round
fill = none（默认）
```

- 主形体：圆角矩形 rx=2~3，或正圆 r=8~9
- 芯片母题：body `7–17`，引脚长度 2.5，对齐半像素
- 两圆同心时间距 ≥ 2，避免 16px 下糊成一团

## 运行时接入

| 路径 | 说明 |
|------|------|
| `etools/ui/resources/icons/*.svg` | 打包进应用的图标源 |
| `etools/ui/icons.py` | 主题感知加载器（`icon` / `app_icon` / `set_button_icon`） |
| `docs/icons/icons/*.svg` | 设计预览副本 |
| `docs/icons/png/` | Logo 多尺寸 PNG + ICO |
| `docs/icons/generate_icons.py` | 唯一生成源，同时写入 docs 与 app |
| `docs/icons/export_png.py` | Logo → PNG/ICO |

加载策略：读 SVG 文本 → 替换 `currentColor` → `QSvgRenderer` 渲染为 `QPixmap` → 缓存。主题切换时 `refresh_icons()` 重绘。

角色取色规则（`objectName`）：

- `accent` → `on_accent`（主按钮上的图标）
- `danger` → `danger`
- 其他 → `text_dim`

## 图标清单

### 品牌

| ID | 语义 | 形态 |
|----|------|------|
| `logo` | 应用主图标 | 深色圆角方 + QFP 芯片 + 引脚 + 烧录闪电 |
| `logo-mark` | 纯标记（无底） | 同上主体，透明底 |

### 工具栏 / 主操作

| ID | 语义 | 形态 |
|----|------|------|
| `open` | 打开固件 | 文件夹 + 下载角标 |
| `program` | 烧录 | 芯片 + 实心闪电 |
| `erase` | 全片擦除 | 芯片 + 斜向橡皮 |
| `verify` | 校验 | 圆 + 勾 |
| `reset` | 复位 | 双向环形箭头 |
| `read` | 读芯片 | 芯片 + 上行箭头 |
| `hex` | Hex 预览 | 字节点阵 |
| `quit` | 退出 | 门 + 出口箭头 |

### 探针与目标

| ID | 语义 | 形态 |
|----|------|------|
| `probe` | 探针 | USB 调试器 + 针脚 |
| `connect` | 连接 | 两端端子 + 链路 |
| `disconnect` | 断开 | 链路切断 |
| `chip` | 目标芯片 | QFP + 引脚 + 定位点 |
| `scan` | 扫描探针 | 小芯片 + 雷达弧 |
| `devices` | 设备管理 | 层叠芯片目录 |
| `refresh` | 刷新 | 双箭头环 |
| `info` | 信息 | 圆 + i |

### 调试视图

| ID | 语义 | 形态 |
|----|------|------|
| `rtt` | RTT 终端 | 窗口 + `>` 提示符 |
| `swv` | SWV 波形 | 坐标轴 + 轨迹 |
| `memory` | 内存 | 堆叠存储条 |
| `save` | 另存为 | 下载 + 托盘 |
| `fill` | 填充内存 | 网格 + 实心块 |
| `blank` | 空白检查 | 虚线方 + 勾 |
| `compare` | 比较 | 双栏对齐 |
| `clear` | 清空 | 垃圾桶线性 |

### 主题与系统

| ID | 语义 | 形态 |
|----|------|------|
| `theme-dark` | 深色 | 月亮 |
| `theme-light` | 浅色 | 太阳 |
| `language` | 语言 | 地球经纬 |
| `success` | 成功 | 绿勾圆（硬编码语义色） |
| `warning` | 警告 | 黄三角（硬编码语义色） |
| `error` | 错误 | 红叉圆（硬编码语义色） |
| `power` | 电源 | 电源符号 |
| `pause` | 暂停 | 圆 + 双竖线 |
| `stop` | 停止 | 圆 + 实心方 |
| `about` | 关于 | 圆 + i |

## UI 触点映射

| 位置 | 图标 |
|------|------|
| 窗口 / 任务栏 / 安装包 | `logo` → `etools.ico` |
| 主工具栏 | open / program / erase / verify / reset / read / hex |
| 固件面板按钮 | 同上对应 |
| 连接按钮 | connect ↔ disconnect |
| 目标信息 / 设备管理刷新 | refresh |
| 日志清空 | clear |
| 主页签 | info / hex / program / devices / rtt / swv |
| 视图菜单 | theme-dark / theme-light / language |

## 语义着色

图标默认按功能着色（`etools/ui/icons.py` 的 `_SEMANTIC_ROLE`）：

| 角色 | Dark / Light | 代表图标 |
|------|--------------|----------|
| accent | `#3B9EFF` / `#1A73E8` | open, program, read, refresh, info… |
| success | `#3DDC97` / `#0F9D6E` | verify, connect, blank, swv |
| danger | `#FF5C5C` / `#D93025` | erase, disconnect, clear, stop, quit |
| warning | `#F5A623` / `#C27803` | reset, fill, pause, power, theme-light |

覆盖规则：

1. `objectName == "accent"` 的按钮 → `on_accent`（蓝底上的深色/白色图标）
2. `objectName == "danger"` 的按钮 → `danger`
3. 其余 → 语义色；未映射则 `text_dim`

主题切换时 `refresh_icons()` 按当前 Theme 重算。

## 使用约定

1. UI 内优先 SVG，通过 `etools.ui.icons` 加载，`currentColor` 跟随主题。
2. 工具栏 18px；面板按钮 16px；标签页 14px；状态 12px。
3. 危险操作（擦除）可用 `danger` 色描边或按钮已有的 `#danger` 样式，图标本身保持中性。
4. 应用窗口图标 / 安装包 / 任务栏使用 `logo` 导出 ICO（16/24/32/48/64/128/256）。
5. 命名：`icons/<id>.svg`，全小写连字符。
6. 新增图标：改 `docs/icons/generate_icons.py` 后重跑脚本，勿手改 SVG。

## 跨平台桌面图标

| 平台 | 资源 | 说明 |
|------|------|------|
| Windows | `docs/icons/png/etools.ico` | 多尺寸 ICO；`setWindowIcon` 用 SVG 渲染 |
| Ubuntu deb | `/usr/share/icons/hicolor/{16..256}x{}/apps/etools.png` + `scalable/apps/etools.svg` | `Icon=etools`；`postinst` 刷新 icon cache |
| Ubuntu AppImage | 同上 + 根目录 `.DirIcon` / `etools.png` | 文件管理器缩略图与 dock |
| 便携包 | `share/icons/hicolor/...` + `install_desktop.sh` | 用户级 `~/.local/share` 安装 |

Linux 运行时：`QApplication.setDesktopFileName("etools")`，与 `.desktop` 的 `Icon=etools` / `StartupWMClass=ETools` 对齐，保证 GNOME/KDE 任务栏图标合并正确。

## 预览

打开 `docs/icons/preview.html` 查看完整图标墙与工具栏模拟。
