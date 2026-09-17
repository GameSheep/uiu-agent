# uiu 产品级差距审计

> 日期：2026-09-16 ｜ 范围：`src/uiu`（25,440 行 / 91 模块）、`tests`（6,968 行 / 56 文件）、CLI、TUI、网关、打包与文档
> 方法：静态扫描 + 可执行探针（本机实跑 pytest / cli_smoke / doctor / 坏配置探针 / 依赖探针）
> 目的：把「水平低」的模糊感受，变成可逐条执行、可验收的问题清单
> 本次审计**未改任何代码**，仅新增本文档

## 审计边界（先声明，避免误信）

- **没有跑真实 LLM 端到端**（本机无 API key）→ 对话质量 / 多轮工具编排只有单测证据。
- **浏览器子系统未执行**（缺 playwright）→ 结论是「本环境无法验证」，不是「确定坏」。
- **没有测覆盖率**：项目未安装 coverage/pytest-cov，也无覆盖率配置，故只能给结构性判断。
- 标注「待验证」的条目是**静态推断**，未实跑。

## 结论摘要

作为「能用的个人 agent」完成度不低；作为「可交付给真实用户的产品」，主要缺口集中在**数据持久化、安全、可观测性**三处。

| 维度 | 就绪度（我的判断） | 一句话 |
|---|---|---|
| 核心 agent 能力 | 8/10 | 循环、工具、中断、压缩齐全，测试厚 |
| 功能完整性 | 6/10 | happy path 覆盖好，异常/空/加载态参差 |
| 工程质量 | 5/10 | 结构可用，但 401 处宽泛捕获、无 lint/类型/日志 |
| 数据与持久化 | 3/10 | 全是裸写文件：无原子写、无锁、无迁移、无备份 |
| 用户体验 | 6/10 | TUI 交互完整；CLI 反馈弱、无 undo |
| 安全与权限 | 4/10 | 有沙箱与确认机制，但网关默认开放、防护是黑名单 |
| 测试 | 6/10 | 458 用例；无覆盖率、无 E2E、8 模块在门外 |
| 部署与运维 | 4/10 | 有 CI 与发布链路；无监控、无日志、无健康检查 |
| 文档 | 5/10 | README 详尽；无 LICENSE、无 API/架构文档 |

**综合「可交付给真实用户」：约 4.5/10。** 3 个 blocker 见文末 P0。

## 实施进度（滚动更新）

| 项 | 状态 | 证据 |
|---|---|---|
| P0-1 网关默认鉴权 | ✅ 完成 | 默认只绑 127.0.0.1（此前硬编码 0.0.0.0）；非本机监听必须有 `UIU_GATEWAY_TOKEN`，否则启动即拒绝（`resolve_bind`），要例外必须显式 `UIU_GATEWAY_INSECURE=1`；新增 `--host`；通用 webhook 的 secret 从可选改为**必填**；启动打印鉴权状态；`uiu doctor` 新增 `channel/gateway-no-token`（可 `--fix` 生成随机 token）。测试：`tests/test_gateway_auth.py`（12 个，含真实 HTTP 401/secret 校验）+ doctor 2 个 |
| P0-2 原子写 + 文件锁 | ✅ 完成 | 新增 `src/uiu/_atomic.py`（原子写 / 双层锁 / 容错读）；改造 sessions、config（含 .env）、cron（jobs + tick 锁）、learning、memory_rag、episodic_memory、suggestions、daemon 的全部状态写入；损坏文件改为「备份为 `.corrupt-<ts>` 再当空处理」；移除 cron 里 pid+TTL 的抢写锁。测试：`tests/test_atomic_io.py`（10 个，含**跨进程**并发与「写入中途失败旧数据仍可读」） |
| P0-3 LICENSE | ✅ 完成 | 新增 `LICENSE`（MIT / GameSheep）；pyproject 补 `authors`；`tests/test_packaging_contract.py::test_license_file_matches_metadata` |
| P0-4 依赖声明修正 | ✅ 完成 | playwright→`[browser]`；uiautomation→`[desktop]`；补齐 numpy/opencv-python（核心）、websockets（browser）、scipy/sounddevice/SpeechRecognition/openai-whisper（voice）；新增扫描测试保证「src 里每个第三方 import 都被声明」；8 个原本在门外的测试模块现在可收集（2 处真实修复 + 显式 skip） |
| P0-5 错误契约 | ✅ 完成 | `uiu config --list` 遇到坏 config.yaml 现在 stderr + rc=2；`test_broken_config_never_reports_success` 同时锁定 show/config/doctor 三者 |
| P0-6 日志体系 | ✅ 完成 | 新增 `src/uiu/log.py`（分级 + `RotatingFileHandler` 5MB×3 + workspace 落盘 + 失败降级）；daemon 手写 append 改为结构化日志；gateway 启动/绑定/鉴权/agent 异常/发送失败/定时任务全部落盘；cron 任务开始-结束-异常落盘；损坏文件备份与 config 解析失败落盘；TUI 启动接上日志。测试：`tests/test_logging.py`（9 个，含轮转、级别、密钥不入日志、日志目录不可用时不崩） |
| P1-9 schema 版本 + 迁移 + 备份恢复 | ✅ 完成 | `schema.py`：config/session/jobs 带版本号并读时迁移（jobs 是真实结构变更，迁移在锁内做）；`backup.py` + `uiu backup/restore`：滚动 7 份、恢复前快照可撤销、拒绝 zip-slip、daemon 每日自动备份。测试：`test_schema_migration.py`(11) + `test_backup_restore.py`(11) |
| P1-7 覆盖率基线 | ✅ 完成 | 实测 53.5%；CI 门禁 `--cov-fail-under=50`；零覆盖模块与最弱 10 个已记录（见 §6.1） |
| 版本单一来源 | ✅ 完成 | npm 0.1.5 → 0.1.7；`test_version_is_single_source` 锁定 pyproject/__init__/npm/CHANGELOG |

### 审计更正（2026-09-17）

原「1.2 同一个坏配置，两个命令两种行为」中关于 `uiu show` 的描述（“rc=2 且无任何输出”）是**我的测量失误**，不是产品缺陷：第一次探针在进程内调用 `main()`，把 `show` 写到 stderr 的内容与下一条命令的输出交错读取，误判为“无输出”。用真实可执行文件并**分离捕获 stdout/stderr** 复测后的事实是：

- `uiu show` → **rc=2 且 stderr 有明确原因** ✅ 行为正确；
- `uiu config --list` → rc=0，且**完全没提配置已损坏** ❌（这是真问题，已修）；
- `uiu doctor --lint` → rc=1，报告走 stdout（报告语义，合理，不改）。

教训写进结论：审计结论必须用**真实入口 + 分离流**验证，管道内捕获容易产生假发现。

---

## 1. 功能完整性

### 1.1 无 API key 时的失败姿势不友好 — 重要
**现状**：CLI 入口有预检（`main.py:315` 打印「还没有 API key」），但库层没有。
**问题**：`llm.py:20` / `llm.py:23` 写的是 `api_key = cfg.resolved_api_key() or "sk-no-key-set"` —— 把占位字符串当 key 交给 SDK。任何绕过 CLI 预检的路径（gateway、cron、daemon、delegate 子 agent）都会带着假 key 发请求，用户看到的是 provider 的 401，而不是「你没配 key」。
**建议**：`resolved_api_key()` 为空时直接抛带修复指引的异常（或在 client 构造处 fail fast），并在 gateway/daemon 启动时做一次前置校验。

### 1.2 同一个坏配置，两个命令两种行为 — 重要
**现状**（实跑探针：真实 `uiu.exe` + 分离捕获 stdout/stderr，config.yaml 写成非法 YAML）：
- `uiu show` → rc=2，stderr 明确写出解析失败位置 ✅
- `uiu doctor --lint` → rc=1，报告 `config/parse-error` + 修复建议（走 stdout 属报告语义）✅
- `uiu config --list` → **rc=0 且完全不提配置已损坏** ❌（已修：现在 stderr + rc=2）

**问题**：错误契约不统一；`show` 静默退出对用户是黑箱，脚本按 rc 判断会误判。
**建议**：统一为「stderr 明确原因 + 非 0 rc」；`doctor` 的做法（错误码 + fix 提示）作为标准。

### 1.3 异常路径普遍缺失或不可读 — 重要
**证据**：`except Exception` 401 处，其中 **155 处直接 `pass` 吞掉**；工具层错误多为 `return f"[error] {type(e).__name__}: {e}"`（`tools.py:64/98/133…`），把 Python 类型名和原始异常直给模型与用户。
**问题**：用户拿到的是 `PermissionError: [WinError 5]` 这类信息，没有「怎么办」。
**建议**：建立错误分类（用户可修复 / 需重试 / 内部错误），用户可修复类必须给动作指引；禁止在关键路径上 `except: pass`。

### 1.4 加载/进度状态：TUI 有，CLI 没有 — 次要
**现状**：TUI 有 spinner、耗时、当前工具名；CLI 的 `publish`/`update`/`doctor --fix`/批量宏回放无进度输出。
**建议**：长任务统一走一个进度输出工具（同一套文案/TTY 检测）。

### 1.5 语言：仅有中文，且无 i18n 机制 — 重要（若面向非中文用户）/次要（若只面向自己）
**证据**：`src/uiu/*.py` 中含中日韩字符的行 **1,830 行**；无 gettext/`_` 之类的 i18n 层（27 处匹配经查为噪声）。
**建议**：要么明确「产品仅支持简体中文」并写进 README/官网，要么现在就为面向用户的字符串引入最小 i18n 层（越晚越贵）。

### 1.6 空/边界状态：TUI 做得不错，CLI 参差 — 次要
**现状**：TUI 有空状态欢迎页、无会话/无命中提示、宽度分档（本轮已加固）；CLI 侧 `uiu sessions` 无参数直接 usage 报错、`skill list` 空列表输出较朴素。
**建议**：给所有「列表类」命令补空状态文案 + 下一步建议。

---

## 2. 工程质量

### 2.1 宽泛异常捕获与静默吞错 — 重要（技术债的根）
**证据**：`except Exception` **401 处**；`except ...: pass` **155 处**；Top：`browser_connect.py` 20、`window_manager.py` 19、`tui.py` 18、`commands.py` 17。
**影响**：故障不可诊断——用户报「没反应」时，日志里什么都没有。
**建议**：分三步——①关键路径（配置/持久化/工具执行/网关）禁止 `pass`，改为记录并上抛；②其余至少记录 `logging.debug`；③加 lint 规则限制新增裸 `except`。

### 2.2 没有日志体系 — blocker（运维层面）
**证据**：`print()` **236 处** vs `logging` **2 处**；无 `basicConfig`/FileHandler/RotatingFile；daemon 手写 append 到 `~/.uiu/daemon.log`，无轮转、无级别、无结构化。
**影响**：gateway 长期跑（服务 telegram/微信），出问题时无任何可回溯记录；磁盘可能被日志撑爆或因禁止写入而丢日志。
**建议**：引入标准 `logging`（级别 + 轮转 + workspace 内路径），daemon/gateway 强制落文件；用户可见错误同时走 stderr。

**已修复（round 5）**：`src/uiu/log.py` 提供 `setup_logging(workspace)`（`RotatingFileHandler` 5MB×3、`UIU_LOG_LEVEL` 控级别、`UIU_LOG_CONSOLE=1` 才打终端、失败即静默降级）与 `get_logger(name)`；daemon/gateway/cron/config/atomic/TUI 全部接入。日志写入 `<workspace>/logs/uiu.log`（daemon 的 `~/.uiu/daemon.log` 保留为子进程 stdout 捕获）。

### 2.3 上帝模块与两套 TUI 并存 — 重要
**证据**：`commands.py` **1,221 行 / 150 处 print**；`desktop_tools.py` 1,185 行（22 处文件写入）；`browser_connect.py` 625 行；同时存在 `tui.py`（classic REPL，377 行）与新 `app/`（Textual）。
**建议**：`commands.py` 按域拆分（config/model/channel/skill/session/macro/publish）；经典 REPL 要么标注为 legacy 并在下个大版本删除，要么明确长期维护（两套 UI 的文案与行为会持续分叉）。

### 2.4 硬编码与不可配置 — 重要
**证据**：`~/.uiu` 硬编码 **27 处**；`localhost/127.0.0.1/端口` 14 处；`timeout=<数字>` **60 处**；`C:\\` 绝对路径 2 处；模型字面量 16 处（部分为 provider 目录，合理）。
**影响**：本会话已两次被 `~/.uiu` 打到（daemon 测试失败、沙箱不可写）；企业/多用户/容器环境必然踩雷；超时不可调导致弱网用户无法使用。
**建议**：统一 `UIU_HOME` + workspace 相对路径；超时与端口进 config；新增「路径解析」单点函数并禁止直接拼 home。

### 2.5 无 lint / 类型 / 格式门禁 — 次要
**证据**：无 ruff/mypy/black 配置；CI 只有 `compileall`（`.github/workflows/ci.yml`）。本会话我自己就写出过「覆写 watcher 漏 super()」这类静态可查的问题。
**建议**：CI 加 ruff（含 bugbear）+ 可选 mypy（先只查 `src/uiu` 新代码）。

---

## 3. 数据与持久化

### 3.1 全是「裸写文件」：无原子写 — blocker
**证据**：`os.replace`/`os.rename` **0 处**；写入点如 `sessions.py:30`（会话 JSON）、`cron.py:42`（jobs.json）、`config.py:240`（config.yaml）、`learning.py:156/205/248`（SKILL.md / 记忆）。
**影响**：进程被杀、断电、磁盘满 → **用户会话/记忆/配置直接损坏且不可恢复**。这是真实用户最不可接受的一类故障。
**建议**：统一 `_atomic_write()`（临时文件同目录 + fsync + `os.replace`），所有 JSON/YAML/MD 落盘走它；损坏文件读取时给出「已备份并重置」而不是直接抛错。

### 3.2 无并发控制（多进程共写） — blocker
**证据**：`flock/lockf/msvcrt/FileLock` **0 处**。而产品形态天然多进程：TUI + `uiu serve`(gateway) + `uiu daemon`(cron) 共享同一 workspace，可能同时写 config.yaml / sessions / MEMORY.md。
**影响**：丢更新（后写覆盖先写）、半写文件、记忆被截断。
**建议**：写入串行化（进程内锁 + 跨进程文件锁）；config 采用「读-改-写」加锁；daemon 与 gateway 对同一资源的使用做显式所有权划分。

### 3.3 无 schema 版本与迁移 — 重要
**证据**：未见存储格式版本字段与迁移函数（6 处 `version` 匹配均为其他语义，如 tool defs）。配置/会话/记忆格式一旦演进，老用户数据没有升级路径。
**建议**：在 config.yaml / sessions / jobs.json 顶层加 `schema: 1`，写迁移表 + 启动时自动迁移 + 迁移前自动备份。

**已修复（round 7）**：新增 `src/uiu/schema.py`（版本探测 + 纯函数迁移表 + `stamp`）；
`config.yaml` / `sessions/*.json` / `cron/jobs.json` 全部带版本号，读时自动迁移（config 迁移后立即落盘）。
其中 **jobs.json 是真实的结构变更**：v0 顶层是裸 list，v1 是 `{schema, jobs}` —— 迁移放在锁内做，
否则「锁内读-改-写」会把 v1 数据当空表覆盖（有专门测试盯着）。

### 3.4 无用户数据备份/导出 — 重要
**证据**：备份相关仅 `uiu update` 的 git tag 回滚点（`commands.py:797`）；用户侧无 `uiu export`/`backup` 命令（`/export` 只导出当前会话 Markdown）。
**建议**：`uiu backup [--to DIR]`（打包 workspace 关键文件 + 版本信息）与 `uiu restore`；自动每日滚动备份保留 N 份。

**已修复（round 7）**：新增 `src/uiu/backup.py` + CLI `uiu backup [--to/--keep/--list]` 与 `uiu restore <zip> [--yes]`。
打包 config/.env/记忆/会话/cron/skills（排除 logs/output/backups/锁/临时文件）；滚动保留 7 份；
**恢复前自动做 pre-restore 快照**（恢复可撤销）；恢复时拒绝 zip-slip 与绝对路径成员（整体拒绝，不写半个文件）；
`uiu daemon` 起手做每日自动备份。

### 3.5 会话无生命周期管理（待验证） — 次要
**现状**：`workspace/sessions/*.json` 只增不减；TUI 支持单个删除。
**建议**：加保留策略（按数量/天数）与「占用空间」展示，删除前提示。

---

## 4. 用户体验

### 4.1 无撤销 — 重要
**证据**：`undo/撤销/rollback` 共 29 处，但都在别处（`uiu update` 的 git tag 回滚、桌面长任务 WAL `desktop_tools.py:607`）。删除会话/技能/宏/渠道**没有撤销**，TUI 里 `d` 删会话是即时的。
**建议**：破坏性操作统一「软删除 + 确认 + 撤销窗口」（TUI 用 toast 带撤销动作，CLI 用 `--yes` 与可恢复的回收站）。

### 4.2 首次体验与引导 — 良好，但有断层
**现状**：有欢迎页 + 模型向导 + 无 key 引导 + `--skip-setup` ✅。
**问题**：向导只在 CLI 首次运行；gateway/daemon 等场景没有「首次配置检查」；TUI 里的权限确认/澄清框与 CLI 的交互不一致（同一问题的措辞两套）。
**建议**：抽一份「首启检查清单」（key、时区、渠道、备份），CLI/TUI/gateway 共用。

### 4.3 反馈一致性 — 次要
**现状**：TUI 有 toast/状态条/未读提示（本轮已完善）；CLI 大量 `print`，成败格式不一（`[ok]/[error]/→` 混用）。
**建议**：定义 CLI 输出规范（成功/警告/错误/下一步四类），并提供 `--json` 便于脚本化。

### 4.4 无障碍 — 次要（但产品化要写清）
**现状**：TUI 全键盘可达、颜色与字形双编码（色盲友好）✅；无屏幕阅读器支持、无高对比/大字号模式；中文 Windows 控制台编码问题在 README 有提示但仍易踩（本机实跑见过乱码风险）。
**建议**：README 明确支持矩阵与限制；TUI 提供 `--no-color`/`--high-contrast`；所有 CLI 输出强制 UTF-8（`PYTHONIOENCODING` 兜底）。

---

## 5. 安全与权限

### 5.1 网关默认无鉴权 — blocker
**证据**：`gateway.py:47-49` `UIU_GATEWAY_TOKEN` 为空即「不鉴权」；`gateway.py:316` 仅当 token 存在时才卡 `/api/*` 与 `/generic/*`；`channels_webhook.py:55` 未配 `secret` 时不校验。
**影响**：能访问端口的人可向 agent 注入任意文本 → 结合本机工具（shell_exec/文件写/微信发送）= **远程代码执行与数据外泄**。默认监听与默认无鉴权叠加，属于必须在上线前解决的项。
**建议**：默认绑 `127.0.0.1`；无 token 时拒绝启动对外监听（或强制生成随机 token 打印一次）；generic webhook 强制要求 secret；启动时打印「当前鉴权状态」并写入 doctor。

**已修复（round 2）**：上述四条全部落地——默认 `127.0.0.1`；非本机 + 无 token 直接 `RuntimeError` 拒绝启动（显式 `UIU_GATEWAY_INSECURE=1` 才放行并警告）；generic webhook 无 secret 一律拒绝投递（`check()` 也标红）；启动打印「监听了哪里 + 鉴权状态」；`uiu doctor` 新增可自动修复的 `channel/gateway-no-token`。

### 5.2 路径防护是黑名单 — 重要
**证据**：`_sandbox.py` 只黑名单 `C:\\Windows`、`Program Files`、`/etc`、`/root`… + 敏感文件名（`.env/.pem/.key/id_rsa`）+ 大小上限。
**影响**：用户家目录其余文件全部可读写——含浏览器 Cookie/Login Data、SSH config、网银/Steam/配置文件；LLM 被注入后可读取并外发。
**建议**：改为「workspace 白名单 + 显式授权目录」，越界一律走用户确认；敏感凭据目录（`AppData\\Local\\Google\\Chrome`、`.ssh`）加入黑名单。

### 5.3 shell 确认策略偏弱 — 重要
**证据**：`confirm.py` `CONFIRM_TOOLS = {send_wechat, shutdown, macro_play}`（`shell_exec` 不在其中）；实际拦截靠 `risk_guardrails.py` 的正则（`BLOCKED_SHELL_PATTERNS` + `rm/del/rmdir/git push --force/drop database` 关键词）。
**现状说明**：好消息是 `tools.py:364` 在 `call_tool` 里调用了 `intercept_tool_call`，即**交互路径也生效**（不是只有 autonomous loop）。
**影响**：正则黑名单易绕过（大小写/编码/管道/脚本文件 `powershell -enc`、`cmd /c`、`; &&` 链式）；一旦绕过，就是无确认的任意命令执行。
**建议**：把「写/删除/网络/进程」类语义提升为**默认需确认**（白名单放行只读命令），确认对话框显示完整命令与 cwd，并支持「本次会话内允许同类」。

### 5.4 密钥明文落盘 — 重要
**证据**：API key 写入 `workspace/.env`（`commands.py:204-211`）；`cryptography` 仅用于企微消息解密（`wecom_crypto.py`），**未用于本地密钥加密**；`.env` 只有工具层 deny。
**建议**：优先接系统凭据库（Windows Credential Manager）；至少给 `.env` 设置仅当前用户 ACL + 文档明示风险；日志/错误信息中对 secret 统一脱敏（`config --list` 已脱敏 ✅）。

### 5.5 无提示注入防线 — 重要
**现状**：网页/邮件/微信内容直接进上下文；`risk_guardrails` 只审「工具参数」，不审「内容里的指令」。
**建议**：对外部内容加来源标注与不可信包装；对「由外部内容触发的工具调用」提高确认等级；高敏工具（发送消息/删文件）不接受纯外部内容驱动的连续调用。

### 5.6 无审计日志 — 重要
**现状**：工具执行（含 shell）没有持久审计记录。
**建议**：写 append-only 审计日志（时间、来源渠道、工具、参数摘要、结果状态、确认人），供追溯与合规。

---

## 6. 测试

### 6.1 有基础、无覆盖率 — 重要
**证据**：56 个测试文件 / 458 个用例（其中 414 可跑通全绿）；**未安装 coverage/pytest-cov**，`pyproject` 无覆盖率配置，CI 不测覆盖率。
**建议**：引入覆盖率基线（先记录现状，再对 `src/uiu/*` 设增量门槛），CI 输出报告。

**已修复（round 6）**：`[test]` extra 加 `coverage` + `pytest-cov`；`[tool.coverage.*]` 配好
source/omit/exclude；CI 增加 `--cov=uiu --cov-report=term-missing --cov-fail-under=50` 门禁。

**实测基线（2026-09-17，本机无法装 coverage，用 stdlib settrace 采集器跑全量套件近似得到）**：
`src/uiu` 语句覆盖 **8000/14952 = 53.5%**。CI 门槛设为 **50**（留 ~3.5pt 余量只防回退）。

**零覆盖模块（6 个，共 1066 行）**：`browser_connect.py`(381)、`browser_explorer.py`(160)、
`safe_update.py`(157)、`browser_self_healing.py`(125)、`skill_installer.py`(107)、`browser_compiler.py`(76)。

**覆盖最弱的 10 个（排除上面的 0%）**：`uia_locator`(5.8%)、`askui_tools`(8.2%)、
`channels_dingtalk`(8.2%)、`voice_tools`(8.7%)、`channels_email`(9.1%)、`channels_discord`(10.9%)、
`channels_slack`(10.9%)、`ime_tools`(13.6%)、`commands.py`(15.5%, 988 行的上帝模块)、
`email_gui`(16.5%)。→ 下一轮补齐顺序：先 `safe_update`/`skill_installer`（纯逻辑、易测），
再 `commands.py`（拆分时顺手补），浏览器栈需要 `[browser]` 依赖才能进 CI。

### 6.2 8 个模块 44 个用例在验证面之外 — 重要
**证据**：
- 4 个浏览器测试模块（26 用例）**无法收集**：`ModuleNotFoundError: playwright`。而 `pyproject` 把 `playwright>=1.40.0` 列为**核心依赖**。
- `uiautomation` 被 `auto_recovery.py:66`、`uia_locator.py:36/137` 导入，但 **pyproject 完全未声明** → 4 个用例必然失败（打包缺陷）。
- `test_desktop_guard::test_daemon_status` 因写入 `~/.uiu` 在受限环境失败（测试不 hermetic）。
- `test_browser_tools::test_browser_tools_with_active_session` 因 `uiu.browser_connect` 未显式导入失败。
**建议**：补齐依赖声明并分层（浏览器相关进 `[browser]`）；测试 hermetic（home 重定向）；对「本机不支持」的子系统用显式 skip + 原因，而不是让整套失败。

### 6.3 无端到端测试 — 重要
**证据**：CI 只跑离线单测 + CLI 冒烟 + Windows 安装态验收；无真实 LLM、真实浏览器、真实桌面操作的 E2E。
**建议**：加一条「真 LLM 最小闭环」E2E（可选 secret，缺失即 skip）；桌面/浏览器 E2E 用录制回放或明确标注「不支持 CI」。

### 6.4 关键风险缺测试 — 重要
**缺口**：并发写/崩溃恢复/迁移/备份恢复/鉴权边界/注入场景。
**建议**：按本文档 P0 项逐条配测试（先写失败测试再修）。

---

## 7. 部署与运维

### 7.1 有 CI，但没有发布门禁 — 重要
**现状**：`.github/workflows/ci.yml` 覆盖 3.12 + 安装 + compileall + pytest + cli_smoke + Windows 安装态验收 ✅。
**缺口**：无 lint、无覆盖率门槛、无版本一致性校验（导致 npm 0.1.5 vs 包 0.1.7 漂移）、无 CHANGELOG 校验。
**建议**：把「版本一致性 + 覆盖率 + lint」做成 PR 门禁。

### 7.2 无监控/健康检查 — blocker（服务化场景）
**现状**：gateway 无 `/health`、无指标、无错误上报；daemon 只有文本日志。
**建议**：`/health`（进程、队列、最近一次错误、渠道状态）；daemon 心跳写状态文件供外部探活。

### 7.3 日志与回滚 — 重要
**现状**：`uiu update` 有 git tag 回滚点 ✅；但无统一日志、无轮转、无级别控制。
**建议**：见 2.2；更新流程补「更新后自检失败自动回滚」的完整闭环与提示。

### 7.4 平台支持不清 — 重要
**现状**：大量 `win32*`/`pyautogui`/Windows 路径逻辑；Linux/macOS 未验证，README 未给支持矩阵。
**建议**：明确「Windows 一等公民，其他平台仅核心可用」并逐条标注哪些命令/工具不可用。

### 7.5 分发链路未端到端验证 — 重要
**现状**：PyPI 0.1.7 可装 ✅；npm 壳（`npm/`）**没有跑通过真实 `npm install`**，且版本号停在 0.1.5。
**建议**：加一条 release checklist（PyPI + npm 双通道 + 全新机器安装验收），版本号单一来源。

---

## 8. 文档

### 8.1 缺法务与协作文件 — blocker（分发）
**证据**：`LICENSE` **不存在**（pyproject 声明 MIT）、无 `SECURITY.md`、`CONTRIBUTING.md`、`CODE_OF_CONDUCT.md`。
**建议**：至少补 LICENSE + SECURITY.md（漏洞上报渠道）；开源协作再补 CONTRIBUTING。

### 8.2 缺架构与技术文档 — 重要
**证据**：无 `ARCHITECTURE.md`、无 API 文档；123 个工具**没有一份工具参考**；gateway 的端点/鉴权/各平台回调格式无文档。
**建议**：①`docs/architecture.md`（模块图 + 数据流 + 进程模型）；②`docs/tools.md`（可由 registry 自动生成，避免再腐烂）；③`docs/gateway-api.md`（端点、鉴权、回调样例、安全默认值）。

### 8.3 文档与代码不一致 — 次要
**证据**：README 写「工具全景（68 个，19 组）」，实测 **123 个**；`cli_smoke.py` 曾钉死「内置工具数 == 68」（本次已修）。
**建议**：数字类内容一律从代码生成或去掉具体数字；CI 加文档数字校验。

### 8.4 缺故障排查手册 — 次要
**建议**：`docs/troubleshooting.md`（无 key、网关不可达、编码乱码、权限拒绝、依赖缺失各自怎么办）。

---

## 优先级路线图

### P0 — 上线前必须（blocker）
1. **网关默认鉴权**：无 token 时仅绑 `127.0.0.1` 或拒绝启动；generic webhook 强制 secret。（5.1）
2. **原子写 + 文件锁**：会话/配置/cron/记忆全部走 `_atomic_write`；多进程写加锁。（3.1/3.2）
3. **LICENSE 文件**：法务底线。（8.1）
4. **依赖声明修正**：`uiautomation` 补声明或删除该路径；`playwright` 分层到 `[browser]`。（6.2/1.x）
5. **统一错误契约**：坏配置下 `show/config/doctor` 行为一致（stderr + 非 0）。（1.2）
6. **日志体系**：结构化 + 轮转 + workspace 内落盘；daemon/gateway 必写。（2.2/7.3）

### P1 — 首个正式版
7. 覆盖率基线与 CI 门槛（6.1）
8. 路径白名单 + shell 语义级确认 + 审计日志（5.2/5.3/5.6）
9. schema 版本 + 迁移 + 备份/恢复命令（3.3/3.4）
10. 架构/工具/网关 API 文档（8.2）
11. 版本一致性门禁（7.1/7.5）
12. 真 LLM 最小 E2E + 子系统显式支持矩阵（6.3/7.4）

### P2 — 体验与长期健康
13. 破坏性操作可撤销（4.1）
14. i18n 决策（要么明确仅中文，要么引入最小 i18n）（1.5）
15. doctor 覆盖依赖/环境/鉴权状态（1.x/5.1）
16. CLI 进度反馈与 `--json`（1.4/4.3）
17. 会话生命周期与空间管理（3.5）

## 建议的验收方式（把清单变成可判定）

每条修复都应附带一个**可执行的判定**，例如：
- 原子写：注入「写入中途 kill -9」的测试，重启后数据仍完整可读。
- 网关鉴权：无 token 启动 → 断言只绑定 127.0.0.1 且 `/generic/*` 返回 401。
- 依赖声明：全新 venv 装 `.[test]` 后，56 个测试文件全部可收集。
- 错误契约：坏 config.yaml 下 `show/config/doctor` 三者都给出明确原因且 rc≠0。
- 版本一致性：pyproject == `__init__` == `npm/package.json` == CHANGELOG 最新版本。
