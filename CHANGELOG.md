# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [Unreleased]

## [0.1.6] - 2026-09-08

### Added
- **全新 full-screen TUI**（textual 重写）：顶栏 / 消息区 / 多行输入区 / 状态条 / 可折叠侧栏分屏布局。
- 消息区**流式 markdown 渲染**（代码块/列表/表格实时高亮），工具调用以单行 `✓/✗ 工具 → 摘要` 展示。
- **多行输入**（Enter 发送、Shift+Enter 换行）、slash 命令补全、Ctrl+R 历史搜索入口。
- 快捷键体系（Ctrl+N 新会话 / Ctrl+S 侧栏 / Ctrl+E 命令面板 / Ctrl+L 清屏 / F1 帮助浮层 等）。
- **首次上手向导**：欢迎屏 → 模型配置引导 → 连通性测试（可跳过），从 `pip install` 到对话不断片。
- **工业级自愈与视觉自动化**：纯 Icon 视觉定位器、UIA 无障碍定位器、屏幕差分自愈交互引擎、意外阻断弹窗消解、画面沉降等待与零崩溃截屏。
- **多显示器与高 DPI 支持**：混合 DPI 缩放换算、光学安全区居中抗漂移。
- **Set-of-Mark (SoM) 视口交互打标**：UIA + OCR 融合标号，支持按标签点击（`som_click_tag`），消除坐标幻觉。
- **进程假死看门狗与长任务恢复**：Windows 消息泵假死检测自愈、预写日志 (WAL) 任务断点事务恢复。
- **空间拓扑相对定位**：支持 `right`、`left`、`below`、`above`、`inside` 五大拓扑关系消除同名元素歧义。
- **输入法防护**：Win32 `imm32` 纯英文状态锁定保护，免疫拼音候选框拦截。
- **边界差分自感知滚动探测**：智能检测列表边界，杜绝死循环。
- **全局急停安全 HUD**：`Ctrl+Alt+Shift+Q` / `Pause` 物理按键毫秒级熔断停机。
- **混合 CDP 驱动**：Chromium 浏览器 DevTools Protocol DOM 选择器与 JS 双模协同驱动。
- **多模态剪贴板与分屏吸附**：CF_DIB 图片直拷、TSV/Markdown 表格互转、双窗平铺吸附。
- **自进化宏编译与情境记忆**：操作轨迹自动编译为可重用 Python 宏，支持自然语言检索重放。

### Changed
- 交互层默认从脚本式 REPL 切换为 full-screen TUI（旧 REPL 保留为 `--no-tui` 与自动降级路径）。
- `cmd_publish` 增加当前版本过滤，防止误传历史归档。

### Fixed
- README / 文档与代码真实行为对齐（工具表、Quickstart、平台边界）。

### Security
- **敏感工具硬确认门**：`send_wechat` / `shutdown` / `macro_play` 在 full-screen TUI 中必须通过内联确认弹窗才执行；无宿主注入时保持原行为。
- 全局物理急停热键（`Ctrl+Alt+Shift+Q` / `Pause`）守护线程，遇突发异常毫秒级物理打断。

[0.1.6]: https://github.com/GameSheep/uiu-agent/releases/tag/v0.1.6
