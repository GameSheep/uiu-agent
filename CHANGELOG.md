# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [Unreleased]

## [1.0.0] - 2026-09-07

### Added
- **全新 full-screen TUI**（textual 重写）：顶栏 / 消息区 / 多行输入区 / 状态条 / 可折叠侧栏分屏布局。
- 消息区**流式 markdown 渲染**（代码块/列表/表格实时高亮），工具调用以单行 `✓/✗ 工具 → 摘要` 展示。
- **多行输入**（Enter 发送、Shift+Enter 换行）、slash 命令补全（Enter 确认选中项）、Ctrl+R 历史搜索入口。
- 快捷键体系（Ctrl+N 新会话 / Ctrl+S 侧栏 / Ctrl+E 命令面板 / Ctrl+L 清屏 / F1 帮助浮层 等）。
- 空态"建议起点"chips：点按即可开始对话。
- **首次上手向导**：欢迎屏 → 模型配置引导 → 连通性测试（可跳过），从 `pip install` 到对话不断片。
- workspace 缺失时自动建到 `~/.uiu/workspace`（home 优先）。
- 敏感工具（send_wechat / shutdown / macro_play）首次调用前**内联确认**。
- Windows 安装态验收脚本 `scripts/verify_windows_install.ps1`。
- 版本一致性校验：`uiu publish` 前核对 `pyproject.toml` 与 `src/uiu/__init__.py`。
- `uiu publish --dry-run`：本地构建并校验 wheel 内容，不上传。

### Changed
- 交互层默认从脚本式 REPL 切换为 full-screen TUI（旧 REPL 保留为 `--no-tui` 与自动降级路径）。
- 模型配置向导复用为首次上手引导的一部分。

### Fixed
- README / 文档与代码真实行为对齐（工具表、Quickstart、平台边界）。

### Security
- **敏感工具硬确认门**：`send_wechat` / `shutdown` / `macro_play` 在 full-screen TUI 中必须通过内联确认弹窗才执行；无宿主注入时保持原行为。
- `--no-tui` / 自动降级到经典 REPL 的路径不绕过确认钩子。

[1.0.0]: https://github.com/GameSheep/uiu-agent/releases/tag/v1.0.0
