# Changelog

本文件记录 ETools 的发布说明。发版前请在对应版本小节下写清 **新增 / 修复 / 改动**，再打 tag。

Release workflow 会读取与 tag 匹配的小节（如 `## [0.1.2]` 或 `## [0.1.2] - 2026-09-13`）作为 GitHub Release 正文。

格式约定：

- 一级版本标题：`## [版本号] - YYYY-MM-DD`（日期可选）
- 分类：`### Added` / `### Fixed` / `### Changed` / `### Removed`
- 未发布内容放在 `## [Unreleased]`

---

## [Unreleased]

### Added

### Fixed

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
