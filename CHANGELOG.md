# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### Added

**产品化补齐（按 docs/audit-2026-09-16-product-gap.md 逐条实施）**

- **网关默认鉴权**：默认只绑 `127.0.0.1`；无 `UIU_GATEWAY_TOKEN` 时拒绝非本机监听（需显式
  `UIU_GATEWAY_INSECURE=1` 才放行并告警）；新增 `uiu serve --host`；通用 webhook 的 secret 改为必填；
  `uiu doctor` 新增可自动修复的 `channel/gateway-no-token`。
- **原子写 + 文件锁**：新增 `src/uiu/_atomic.py`（同目录临时文件 + fsync + os.replace；进程内 RLock +
  跨进程 OS 锁；锁内读-改-写；损坏文件备份为 `.corrupt-<ts>`），全部状态文件（sessions/config/.env/
  cron/记忆/建议/情景记忆/daemon pid）改走它；cron tick 的 pid+TTL 抢写锁换成真正的 OS 级锁。
- **日志体系**：新增 `src/uiu/log.py`（`<workspace>/logs/uiu.log`，5MB×3 轮转，`UIU_LOG_LEVEL` 控级别，
  `UIU_LOG_CONSOLE=1` 才打终端，失败即降级）；daemon/gateway/cron/config/TUI 全部接入。
- **schema 版本与迁移**：`config.yaml` / `sessions/*.json` / `cron/jobs.json` 带版本号，读时自动迁移
  （jobs.json 由裸 list 变为 `{schema, jobs}`，迁移在锁内进行）。
- **备份 / 恢复**：`uiu backup [--to/--keep/--list]` 与 `uiu restore <zip> [--yes]`；滚动保留 7 份、
  恢复前自动快照（可撤销）、拒绝 zip-slip 与绝对路径；`uiu daemon` 每日自动备份。
- **覆盖率门禁**：`[test]` 加 coverage/pytest-cov，CI 增加 `--cov-fail-under=50`（实测基线 53.5%）。
- **LICENSE**（MIT）与 pyproject `authors`；补齐 10 个未声明的第三方依赖（playwright 移入 `[browser]`、
  uiautomation 移入 `[desktop]`、numpy/opencv/scipy/websockets/sounddevice 等），并加测试保证
  「src 里每个第三方 import 都已在 pyproject 声明」。
- **错误契约**：坏 config.yaml 下 `uiu config --list` 不再静默返回 0（stderr + rc=2）。
- 版本单一来源测试（pyproject == __init__ == npm == CHANGELOG）。

**TUI 重做（对标 OpenClaw / Hermes 的精致度）**

- **设计令牌层** `src/uiu/app/theme.py`：4 套内置主题（`uiu-dark` / `uiu-mono` / `uiu-neon` / `uiu-solar`）、
  统一字形表与间距常量，颜色不再散落在各 widget 里硬编码。
- **主题选择器** `Ctrl+T`（或 `/theme`）：↑↓ 实时预览、Enter 应用、Esc 还原；选择持久化到
  `workspace/config.yaml` 的 `tui.theme`（新增 `AppConfig.tui`）。
- **自定义配色 `tui.colors`**：覆盖任意色位（其余继承所选主题），派生 `uiu-custom`；
  切换基础主题时以新主题为底重新派生；主题面板会提示当前覆盖了哪些色位。
- **顶栏**两行品牌条（品牌字标 + agent / 模型，工作区 + 工具·技能·版本·会话）。
- **消息区**：角色字形 + 名字 + 时间戳 + 左侧角色色竖线；流式回复带 `▍` 光标与 `正在生成…`；
  首屏为产品卡（品牌 + 定位语 + 能力徽章 + 状态）与「从这些开始」建议卡，并带**继续上次会话**卡片。
- **推理过程折叠**（`ThoughtRow`）：`✻ 思考过程 N 字 · 耗时`，超过 160 字在回合结束后自动收起，
  点击展开/收起。
- **工具调用实时行**：发出即渲染 `⚙ 名 ⠋ 运行中`（0.25s tick 转动），返回后原地变成结果行
  （耗时 + 可展开完整入参与返回）。
- **Markdown 排版**：代码块底纹 + 左侧色条、行内码底色、分级标题配色、引用竖线、表格网格线。
- **会话切换器** `Ctrl+X` / `/sessions`：列出会话（轮数 + 当前标记），Enter 载入并重渲染历史，`d` 删除。
- **会话用量面板** `Ctrl+U` / `/usage`；**运行状态面板** `/status`（模型 / API key / 渠道 / MCP / 主题…）；
  两者共用通用 `InfoPanel` 基类。
- **对话内检索** `Ctrl+R`：过滤当前对话（角色 + 时间 + 摘要，命中词加粗），Enter 跳到该消息并高亮；
  之后 `F3` / `Shift+F3` 可在命中之间循环跳转（状态条显示 `命中 2/5`）。
- **跨会话检索** `/search <关键词>`：输入即搜（250ms 防抖、本地毫秒级），命中显示会话 / 角色 / 摘要 / 上下文，
  Enter 打开会话并跳到命中消息。
- **复制**：`Ctrl+Y` 复制上一条回答、`/copy` 同、`/copy all` 导出整段会话 Markdown；
  新增 `app/clipboard.py`（pyperclip → Windows `Set-Clipboard` 兜底，失败返回原因）。
- **状态条轻提示**：复制、主题切换等瞬时反馈显示在状态条，3 秒自动消失（失败红色、6 秒）。
- **运行时长与实时活动**：状态条 `⠋ running 3s`；输入区提示行显示当前工具名。
- **未读提示**：手动上滚期间有新内容时状态条显示 `↓ 新内容 · Ctrl+End`，`Ctrl+End` 回到底部。
- **长会话折叠**：消息区常驻最近 60 条，更早的折成顶部一行；点击**按页**加载（每次 60 条，硬上限 400 条）。
- **侧栏最近会话**：最近 3-4 个会话（相对时间）一键切换 + `全部会话…`；
  `sessions.recent_sessions()` 只读文件名与 mtime，不解析 JSON，可安全高频刷新。
- **输入历史** `↑`/`↓`；**长文本粘贴折叠**（>6 行 / 600 字折叠为占位符，发送时还原全文）。
- **窄终端自适应**：<88 列自动收侧栏、<74 列顶栏单行、状态条按宽度分档丢信息、
  提示行与首屏徽章/建议卡同步收缩；空态从顶部看起。
- **CLI**：`uiu config --theme <name>` / `--color SLOT=#RRGGBB`（含合法性校验与清除）；
  `uiu show` 展示 tui 偏好；`uiu doctor` 校验 `tui.theme` 与 `tui.colors`，
  `--fix` 可重置非法主题、删除非法/未知色位。
- **检索浮层显示命中数**：对话内检索底部显示 `命中 N 处`。
- **命令面板升级为真·命令面板**：`Ctrl+E` 现在把 **动作**（新会话 / 切换会话 / 切换主题 / 搜索当前对话 /
  跨会话检索 / 会话用量 / 运行状态 / 复制回答 / 导出会话 / 保存 / 压缩 / 技能 / 定时任务 / 建议 /
  回到底部 / 侧栏 / 帮助）、**最近会话**与全部 **slash 命令**放在一起模糊过滤，条目左侧标类别、
  右侧是快捷键或说明，底部显示条目数；动作与会话排前面，slash 命令按字典序殿后。
- **状态条显示 token 估算**：宽屏档位下在上下文进度后追加 `=14ktok`。
- **会话滚动位置记忆**：切走时记住滚动偏移，切回来仍在原处（`_session_scroll`）。
- **滚到顶自动补历史**：长会话滚到顶部会自动加载上一页（60 条），并用「锚点行」把视口钉回原位；
  只有**用户上滚**才会触发（程序化滚动与重建过程中的 `scroll_y` 归零不算），展开期间另有一层挂起标记，
  避免连环补页。
- **检索作用域切换**：`Ctrl+R` 浮层按 `Tab` 在「全部 / 对话 / 命令输出」之间切换，
  底部显示当前范围与命中数；匹配同时覆盖内容与来源标签（搜 tools 能找到 `/tools` 输出）。
- **界面导览文档** `docs/tui-tour.md`：11 个界面各配一张预览图 + 说明，README 直接引用；
  `docs/preview/*.svg` 入库（PNG 仍为本地产物）。
- **命令面板按最近使用排序**：本次会话里用过的条目自动提到最前（最多记 8 条，去重）。
- **headless 界面预览器** `scripts/tui_preview.py`：用假 client 驱动真实界面，把 9 个状态
  （首屏 / 对话 / 窄屏 / 帮助 / 命令面板 / 会话切换 / 用量 / 状态 / 检索）导出成 SVG+PNG 到
  `docs/preview/`，方便设计核对；另加 2 个冒烟测试。
- **可点行的手型光标与悬停底色**：工具行 / 思考块 / 可折叠命令输出加 `-clickable`
  （`pointer: pointer` + hover 底色），能点的地方一眼可见。
- **对话内检索覆盖命令输出**：`Ctrl+R` 现在也能搜到折叠的 `/help`、`/tools` 输出，
  命中项以 `❯ /tools` 标注来源。
- **终端窗口标题跟随会话**：`uiu — <会话名> · <模型>`，切换/新建会话时同步。
- **斜杠命令长输出折叠**：新增 `OutputRow`——`/help`（21 行）、`/tools`（123 行）这类输出折成
  `❯ /help 21 行 [点击展开]`，展开后包在代码围栏里按原文等宽对齐（markdown 会把普通换行重排成一段）。
- **每条回答可单独复制**：助手/错误消息头部有 `⧉` 按钮（用户消息不加，自己写的不需要复制）。
- **`/export [名字]`**：会话导出为 Markdown 落到 `workspace/exports/`，空会话拒绝导出；
  已加进命令面板与帮助浮层。
- 新增 50 个 TUI 测试（主题 / 首屏 / 折叠 / 检索 / 剪贴板 / 自适应 / 状态条…）。

### Changed
- **斜杠命令不再阻塞界面**：命令派发改到工作线程（`asyncio.to_thread`），`/compact`、`/cron run`
  这类慢命令执行期间界面照常响应；期间状态条显示 `running`、输入区提示 `/compact 执行中`，
  结束后自动复位并禁止重复提交。
- **流式渲染节流**：markdown 重排从「每个 token 一次」改为最多 80ms 一次（回合结束强制 flush），
  长时间流式输出不再抖动。
- `session.search_sessions` 的上下文取样跳过 system 消息（不再把整段人设当成「上下文」）。

### Fixed
- **多轮边界测试揪出的 12 个问题**（新增 `tests/test_app_edgecases.py`，35 个用例覆盖异常数据 / 异常时序 / 极端布局）：
  - **空列表按 Enter 毫无反应**：命令面板、会话切换器、两种检索浮层在「无命中 / 无会话」时 Enter 被 ListView 吞掉，
    面板看起来卡死；现在一律正常关闭（会话切换器/检索浮层改用优先级 Enter 兜底）。
  - **静默丢弃操作**：回合进行中再发消息 / 切会话 / 开新会话原本什么都不做，现在用红色轻提示说明原因。
  - **重建后残留的检索命中**：切会话、`/new` 之后 `F3` 仍在旧气泡列表里跳（提示「命中 1/4」却哪里都没动）；
    现在随重建一起清空。
  - **空会话的 `/copy all`**：会把只有一个标题的空文档塞进剪贴板，现在明确回「没有可复制的内容」。
  - **历史回溯弹出补全菜单**：`↑` 取回以 `/` 开头的历史时，异步 Changed 消息让布尔标记过期；
    改为按写入文本精确抑制一次。
  - **卸载后仍会投递的消息**：折叠展开 / 发送 / 会话载入 / 复制在应用退出后触发会抛 `NoMatches`，
    现在统一走 `_chat()` 空值保护。
  - 其余为配套 API（`clarify.get_ask_handler` / `confirm.get_confirm_handler`）与测试自身的修正。
- **输入区焦点提示**：`#composer-shell:focus-within` 高亮，之前输入框因为去掉了边框而完全没有焦点反馈。
- **超大工具返回不再拖垮渲染**：展开的工具行正文超过 4000 字会截断并标注「已截断，完整返回共 N 字」。
- **折叠条到上限不再假装可点**：到 `MAX_RENDER` 时文案改为「已达上限（400 条）」，不再显示「点击展开」。
- **清掉死代码**：删除未被引用的 `src/uiu/app/app_part1.py`、`ChatView` 里未使用的 `Binding` 导入与 `Bubble._tool_rows`；
  滚动钩子补上 event 形参，与 Textual 的消息派发签名一致。
- **主题可读性有测试兜底**（新 `tests/test_theme.py`）：4 套配色逐一校验 `#RRGGBB` 格式、
  正文对比度 ≥ 4.5:1（WCAG AA）、强调色 ≥ 3:1、三层背景不塌陷、dark 标记与背景亮度一致。
- **恢复滚动条同步**：覆写 `ChatView.watch_scroll_y` 时漏了 `super()`，导致滚动条位置 / 锚点 /
  滚动重绘三件事都不再更新（本轮自查发现）。
- **不再谎报可中断**：斜杠命令无法被 Esc 打断，执行期间的输入区提示改为「完成后自动返回」
  （原先显示「Esc 中断」但按了没反应）；`Composer.set_busy(cancellable=False)` 表达这个语义。
- textual 主题变量 `$boost` 在本版本解析为透明，导致分隔线 / 背景 / 卡片底色不显示（改用 `$panel-lighten-*`）。
- **流式消息顺序错乱**：回答气泡原先在发起回合时就预建，导致「思考块 / 工具行」被排到回答之后；
  改为第一个文本片段时惰性创建，并消除 `begin_thought` / `begin_assistant` 在首个 await 前
  未设置引用的竞态（重复挂载 / 顺序颠倒）。

## [0.1.7] - 2026-09-08

### Added
- **多浏览器生态接管**：无缝支持 Windows 预装的 **Microsoft Edge**、**Google Chrome** 以及 **Brave** 浏览器。
- **系统默认浏览器免配置识别**：读取注册表 `UserChoice` 自动侦测默认浏览器，支持 `browser="auto"` 零配置一键接管。
- **已安装浏览器全局扫描体检**：`browser_list_installed` 工具，枚举系统所有可用浏览器、可执行文件路径及当前运行态。
- **智能标签页管理 (`browser_tabs_manage`)**：
  - 标签页枚举与模糊匹配（按索引或标题/网址关键字）；
  - 防重复开标签与置顶激活（已打开同域名/页面时自动切换复用，杜绝标签页泛滥）；
  - 安全关闭指定标签页。
- **DOM 结构化极速提取 (`browser_content_extract`)**：
  - `markdown` 模式直接将网页正文提取为整洁的 Markdown 文档；
  - `table` 模式自动将 HTML `<table>` 转换为标准 Markdown 数据表格；
  - `text` / `html` 模式与自定义 JavaScript 脚本执行 (`browser_eval_js`)。
- **键鼠免干扰执行上下文守卫 (`desktop_guard.py`)**：
  - 静默后台状态（无用户对话、非定时任务）物理拦截受控键鼠操作；
  - 定时任务到点避让正在物理键鼠操作的人类用户；
  - 修复后台意外抢夺焦点与键鼠吞键问题。

### Changed
- `src/uiu/browser_tools.py` 底层统一接入宿主浏览器 CDP 会话，保证全局浏览器操作一致性。

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

[0.1.7]: https://github.com/GameSheep/uiu-agent/releases/tag/v0.1.7
[0.1.6]: https://github.com/GameSheep/uiu-agent/releases/tag/v0.1.6
