# 设计：uiu v1.0 —— textual TUI 重写 + 首次上手体验

日期：2026-09-07 · 状态：**已实现**（2026-09-07，验收全绿：204 pytest + smoke + Windows 安装态）

## 背景与目标

uiu 已具备较完整的 agent 能力：68 个内置工具（已注册且经 194 个 pytest + cli_smoke 全绿验证）、
SOUL/skills/memory 渐进披露、多渠道 gateway、cron、宏、OCR 桌面自动化、自学习、MCP 接线等。
但用户反馈"用起来太 demo 简陋"，核心痛点在**交互体验**与**首次上手**两处：

- TUI 是"Rich 打印 + prompt_toolkit 单行输入"的脚本式 REPL：输出与输入互相涂抹、token 裸流、
  无分屏、无快捷键体系、无主题、面板操作一律退出终端敲命令。
- 新用户装完要手动配 key/workspace、文档多处与真实行为不符，缺少"开箱即用"引导。
- 目标：公开发布（PyPI 已发 0.1.5，名称 uiu），主战场 Windows。

一句话目标：把 uiu 升级为 Windows 上"第一眼就像个应用"的 full-screen TUI，
同时让陌生用户从 `pip install uiu` 到第一次对话全程不断片，以 **v1.0.0** 为发布目标。

## 范围

### 做
1. TUI 换 textual 重写为分屏 full-screen 应用（消息区/输入区/顶栏/状态条/可折叠侧栏）。
2. 首启向导与"零配置到能聊"体验（欢迎屏→模型引导→连通性测试→空态建议 chip）。
3. Windows 安装态全链路验收 + CHANGELOG + 版本三处一致校验。
4. README/文档与真实能力对齐（Quickstart 一镜到底、工具表逐个核对）。
5. 旧 REPL 保留为降级路径（非 tty/管道/textual 初始化失败时自动回退）。

### 不做（本轮）
- Web/GUI 面板。
- 重写对话引擎/沙箱/工具（已全绿，只加包装不改行为）。
- macOS/Linux 桌面自动化（仅保证"装+聊"可跨平台，桌面能力仍 Windows-only）。
- 功能清单缺最后一公里的部分（browser 降级/voice/RAG 等）：交互相关以文档口径对齐为准，
  已注册工具逐个核对注册表与 README 工具表。
- npm 侧（uiu-agent）发行验收：本轮专注 PyPI，功能完善后再做。

## 技术架构

### 依赖
- 新增 **textual**（纯 Python，PyPI 最新 8.2.8，需 Python ≥3.9；环境 3.13.7 满足，Windows 支持完整）。
- rich / prompt_toolkit 保留（其他模块仍依赖）。

### 新增包 src/uiu/app/
```
src/uiu/app/
├── __init__.py        # 导出 run_app()
├── app.py             # UiuApp(Application)：布局、生命周期、全局键绑定、首启检测
├── widgets/
│   ├── chat_view.py   # 消息区（流式 markdown、气泡、工具行折叠/展开、空态 chip）
│   ├── composer.py    # 多行输入（multiline、slash 补全、发送键、历史）
│   ├── statusbar.py   # 状态条
│   └── sidebar.py     # 侧栏（会话/快捷命令/命令面板，可折叠）
└── agent_worker.py    # run_turn 包装到工作线程，事件回 textual 主线程
```

### 关键桥接
- agent.py 的 run_turn 接受 on_text/on_tool_call/on_tool_result/on_notice 回调，
  天然适配 textual 的 post_message → 对话引擎不改行为，仅包 worker 线程 + 队列事件。
- 与 slash / skills / sessions / learning / clarify 复用现有注册表接口，不改协议。

### 降级路径
- `--no-tui` 显式禁用；非 tty / 管道 / textual 初始化异常时自动回退旧 `tui.repl`。
- main.py 默认走新 UiuApp.run()。

## 界面布局与交互

### 屏幕布局
顶栏(角色名 · 模型 · workspace · 工具/技能数) / 消息区+可折叠侧栏 / 多行输入区 / 状态条。
侧栏默认收起（窄终端自动隐藏），ctrl+s 或 /sidebar 开合。消息区与输入区分开，
不再像旧 REPL 那样输出与提示行互相涂抹。

### 消息区 ChatView
- 用户/agent 消息用**轻气泡 + 角色色块**样式（用户侧确认过要气泡观感）。
- agent 回复**流式增量渲染 markdown**（代码/表格/列表高亮；80ms 节流重建，非逐 token 全量重排）。
- 工具调用单行 `⚙ read_file → ✓ 摘要`（失败红 ✗），默认折叠、enter 展开/收起完整入参/结果。
- 滚动自动跟随（stick）；上滚停跟；pgup/pgdn/home/end。
- 空态：一句引导 + 3-5 个"建议起点"chip（点按即发送）。

### 输入区 Composer
- 多行输入：Shift+Enter 换行、Enter 发送（可配置 tui.enter_sends）。
- slash 补全：输入 / 弹补全菜单（命令/工具/skill），Tab/上下选、Enter 确认。
- 发送中锁定；Esc 中断当前 agent 回合。
- Up/Down 历史；ctrl+r 历史搜索浮层。

### 快捷键
ctrl+n 新会话 · ctrl+s 侧栏 · ctrl+r 历史搜索 · ctrl+l 清屏 ·
ctrl+e 命令面板（模糊搜 slash） · ctrl+q/ctrl+c(空输入) 退出 ·
f2 状态条开关 · esc 中断 · /? 帮助浮层。

### 视觉
- 一套默认深色主题（沿用 cyan/green 品牌色），配色集中常量便于后续 tui.theme 配置。
- 窄终端（<90 列）自动隐藏侧栏、气泡单列。

### 错误与状态
- running=黄点 / error=红点；错误 hint（换 key//clear/超时）内联显示在消息区。
- agent 回合跑工作线程 → 等待回复时 UI 不卡（打字/滚动/快捷键可用）。

## 首次上手体验

### 首启流程
第一次跑 `uiu`（或 workspace 不存在 / 无 key）：
1. 欢迎屏：说明 uiu 是什么、做什么、约 1 分钟。
2. 复用现有 cmd_model 交互向导（已成熟），包欢迎上下文。
3. 引导完成 → 进 TUI 前**先跑连通性测试**（最小请求，~1-2s，可跳过）：
   通→进聊天；不通→明确错误（401/超时/域名）与修法。
4. 可随时 /quit；`--skip-setup` 跳过（高级用户）。

### 零配置路径
- workspace：找不到时建在 `~/.uiu/workspace`（home 优先 + 提示），落好 SOUL/IDENTITY/USER/MEMORY 模板。
- 无 key 也能起来看界面；模型引导含"本地 Ollama 免 key"与 DeepSeek 等一键填 key。

### 会话内引导
- 空态 3-5 建议 chip：看磁盘/内存、微信文件传输助手、录宏、列技能。
- /help 输出改为分屏内可滚动帮助（命令/快捷键/工具/slash 分区）。
- 状态条冷启动提示 `/help 看命令 · ctrl+e 命令面板`。

### 首次对话护栏
- send_wechat / shutdown / macro_play 首次调用时消息区内联确认浮层（yes/no）——兑现"调用前确认"。

### 文档对齐
- README Quickstart 一镜到底 + 截图式描述；工具表与实际注册表逐个核对。
- README 声称 vs 代码不符项：交互相关改文档口径；已注册工具逐个核对修正。
- workspace 模板自带示例技能/示例记忆。

## 工程与分发

### 版本与发布门禁
- 版本 → **1.0.0**（pyproject / src/uiu/__init__.py / npm/package.json 三处一致）。
- 新增 CHANGELOG.md（Keep a Changelog 风格；记录 TUI 重写/首启/文档对齐/测试红线）。
- `uiu publish` 前自动校验三处版本号一致，不一致拒绝。
- `uiu publish --dry-run` 本地构建 wheel 校验内容再真传。

### Windows 安装态验收
- scripts/verify_windows_install.ps1：全新 venv `pip install .` → uiu version → uiu init 临时目录
  → uiu doctor → uiu show → 无头 TUI 冒烟（textual pilot 或 --no-tui）→ 退出码 0。
- CI（GitHub Actions windows-latest）：全量 pytest + cli_smoke + 安装态脚本。
  （用户已授权查看/修改 .github/workflows/ci.yml。）

### 测试红线
- 新 TUI 测试用 textual pilot 离线驱动（假 client/假 run_turn），不依赖真 LLM。
- 不得绕过 uiu.tools 注册表直接 import 底层模块（延续纪律）。
- 194 现有测试保持全绿。

### 仓库整理
- 未提交模块（doctor/macros/suggestions/wecom_crypto 等）、npm/、.commandcode/ 一并提交干净。
- 本设计文档入 docs/superpowers/specs/2026-09-07-tui-and-onboarding-design.md 并提交。

## 验收红线
1. `import uiu.tools` 通过，工具数可数（≥68）。
2. 194 现有 pytest + cli_smoke 全绿。
3. textual TUI 可无头启动（pilot 冒烟）且 /help、slash 补全、空态 chip、折叠工具行可测。
4. Windows 安装态脚本在干净 venv 从 pip install . 到 doctor/show/TUI 冒烟全绿。
5. 三处版本号一致 = 1.0.0；CHANGELOG 存在。
6. README Quickstart 与工具表与真实行为一致。
