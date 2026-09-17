# uiu

> 一个**最小可跑**的个人 IP agent 骨架。借鉴 Hermes Agent 的 SOUL/skills/memory 模式，但砍到只剩核心。

## 它能做什么

- 跟你多轮对话，记住上下文（同一会话内；`/save` 可跨会话 resume）。
- 自动调用 123 个内置工具（文件/shell/后台进程/屏幕 OCR/桌面控制/宏录制回放/系统/微信/输入法/子 agent 派发/联网搜索/浏览器/MCP 动态工具…），完整清单见 [docs/tools.md](docs/tools.md)。
- skill 渐进披露：system prompt 只带索引，用 `skills_list` / `skill_view` 按需取全文。
- `cron` 定时任务：到点自动跑 agent 并落盘（`uiu serve` 内每 60s tick）。
- 不确定就反问：`clarify` 工具阻塞等你回答再干活。
- 你的"人设"写在 `workspace/SOUL.md` 里——改它，agent 就变样。
- 长记忆写在 `workspace/MEMORY.md`——对话里 `/memory <note>` 一键追加。
- **自我学习（Hermes learning loop）**：主动记记忆、沉淀技能、改进技能。
- **屏幕自动化（OCR，免视觉模型）**：说"点提交按钮"它就能点。
- **完整 CLI**：配置模型（34 provider）、加 skill、加 channel（Telegram/飞书/企微/钉钉/Discord/Slack）、更新代码。
- **可发布到 PyPI**：`uiu publish` 一行构建 + 上传，全世界 `pip install uiu`。

## 语言支持

**当前只支持简体中文**：界面文案、CLI 提示、错误信息、文档全部是中文，没有 gettext/i18n 层。
`--json` 输出的**键**是英文且稳定（`ok` / `command` / `data` / `error`），脚本不受文案改动影响。

这是一个明确的产品决策，而不是「还没来得及翻译」：与其做半套翻译，不如把中文写清楚。
新增的用户可见提示必须是中文，有测试盯着（`tests/test_language_policy.py`）。

## 文档索引

| 文档 | 内容 |
|---|---|
| [docs/architecture.md](docs/architecture.md) | 分层、进程模型、一次对话的数据流、状态文件与写入约定、安全模型 |
| [docs/platform-support.md](docs/platform-support.md) | 平台支持矩阵（Windows 一等公民；哪些能力在 Linux/macOS 不可用） |
| [docs/tools.md](docs/tools.md) | **123 个内置工具**参考（自动生成） |
| [docs/gateway-api.md](docs/gateway-api.md) | 网关端点、鉴权矩阵、各平台回调、返回约定 |
| [docs/troubleshooting.md](docs/troubleshooting.md) | 按症状排查（启动/密钥/权限/数据/环境） |
| [docs/tui-tour.md](docs/tui-tour.md) | 界面导览（11 个界面配图） |
| [docs/audit-2026-09-16-product-gap.md](docs/audit-2026-09-16-product-gap.md) | 产品级差距审计与实施进度 |

## 屏幕自动化（OCR 点击，不需要视觉模型）

```
"帮我点击网页上的提交按钮"     → agent 调 click_text
"屏幕上现在有什么？"           → agent 调 screen_read_text
"输入用户名然后点登录"          → click_text + type_text + click_text
```

**技术链路**：PyAutoGUI 截图 → RapidOCR 识别中文文字 → 按文本找坐标 → PyAutoGUI 点击。
不需要视觉模型，纯 OCR 定位——中文识别准确率 99%+。

工具：
| 工具 | 干嘛 |
|---|---|
| `click_text` | 点击屏幕上指定文字的按钮/元素 |
| `screen_read_text` | 读取整个屏幕的可见文字 |
| `type_text` | 在当前输入框输入文字 |
| `press_key` | 按键/组合键（enter、ctrl+s） |

## Windows 桌面控制（通用 GUI 原子操作 + 微信闭环）

```
"切到微信"                 → agent: window_list + window_focus
"显示桌面"                 → agent: keyboard_shortcut(['win', 'd'])
"打开资源管理器"           → agent: app_launch('explorer')
"点任务栏的 Chrome"        → agent: screen_ocr_find + mouse_click_at
"现在开着什么窗口？"        → agent: window_list
"给文件传输助手发消息"      → agent: send_wechat（8 步闭环，见下）
```

工具：
| 工具 | 干嘛 |
|---|---|
| `window_list` | 列出所有可见窗口（标题/HWND/位置） |
| `window_focus` | 按标题关键字置顶激活窗口 |
| `app_launch` | 启动程序/打开文件/URL（无 shell 解析，防注入） |
| `screen_ocr_find` | 屏幕找字返坐标（可滚动查找） |
| `mouse_click_at` | 按绝对坐标点击（含双击） |
| `mouse_scroll_at` | 指定位置滚轮 |
| `text_paste` | 剪贴板粘贴中英文（防输入法干扰） |
| `keyboard_shortcut` | 组合键/单键（校验合法键名） |
| `send_wechat` | 微信 8 步闭环发送（定位→双击弹窗→标题核对→粘贴→输入区核对→发送→聊天区核对，任一步失败即停） |

## 系统管理（7 个系统工具）

```
"电脑卡不卡 / 内存多大 / 还有多少电"  → system_info
"帮我关机 / 重启 / 睡眠"              → shutdown（需确认）
"网通不通"                            → check_network
"我复制了什么"                        → clipboard_get
"打开哔哩哔哩 / 搜索今天的新闻"        → open_url
"截个图"                              → take_screenshot
```

| 工具 | 干嘛 |
|---|---|
| `system_info` | CPU/内存/磁盘/电池/开机时长（实测：31GB 内存、97% 电量、3 磁盘） |
| `shutdown` | 关机/重启/注销/睡眠（**必须先确认**） |
| `check_network` | ping 测试（实测 baidu 34ms） |
| `clipboard_get/set` | 读写剪贴板 |
| `open_url` | 浏览器打开网址或搜索 |
| `take_screenshot` | 截屏存桌面 |

## 宏录制回放（按键精灵式，AI 可生成宏）

```
"帮我把这个操作录成宏"          → agent 调 macro_record（F9 结束）
"跑一下填表宏"                   → agent 调 macro_play（执行前确认）
"写个宏：每 5 分钟点一次刷新"    → agent 直接生成宏 JSON 文件再回放
```

**把重复性 GUI 劳动变成可复用宏**：录制一次人工操作（点击/按键/滚轮），之后随时一键回放。
区别于按键精灵的地方：宏是 `workspace/macros/<name>.json` 纯文本——**AI 可以直接读写生成宏**，
你说需求它就写出步骤序列，再自动执行。

| 工具 | 干嘛 |
|---|---|
| `macro_record` | 录制宏（F9 停止；只记点击/按键/滚轮 + 间隔，不记鼠标轨迹） |
| `macro_play` | 回放宏（甩鼠标到左上角或按 F9 可紧急中止） |
| `macro_list` | 列出宏 |
| `macro_remove` | 删除宏 |

CLI：`uiu macro record 填表 --desc "登录后填表"` / `uiu macro play 填表 --speed 2` / `uiu macro list`。

宏文件可直接编辑或由 AI 生成（步骤类型：click/key/type/wait/scroll/hotkey，各带 `delay_before` 间隔）。

## 工具全景

> **123 个内置工具**的完整参考（名称 / 说明 / 参数 / 是否需要确认）见
> **[docs/tools.md](docs/tools.md)** —— 该文件由 `scripts/gen_tools_doc.py` 从注册表生成，
> CI 会校验它与代码一致，所以这里的数字不会过期。

| 类 | 工具 |
|---|---|
| 基础 | shell_exec / read_file / write_file / read_spreadsheet |
| 后台进程 | proc_run / proc_log / proc_kill / list_procs（耗时命令不阻塞） |
| 自学习 | memory_add / memory_recall / memory_replace / memory_remove / skill_create / skill_improve |
| skill 索引 | skills_list / skill_view（渐进披露，按需取全文） |
| 会话检索 | session_search（跨已存会话关键词检索，零 token 秒回） |
| 宏录制 | macro_record / macro_play / macro_list / macro_remove（按键精灵式，AI 可生成宏） |
| 澄清 | clarify（反问用户并阻塞等回答） |
| 屏幕 OCR | click_text / screen_read_text / type_text / press_key / ocr_region / click_in_region |
| 桌面 | window_list / window_focus / app_launch / screen_ocr_find / mouse_click_at / mouse_scroll_at / text_paste / keyboard_shortcut |
| 系统 | system_info / get_time / shutdown / check_network / clipboard_get/set / open_url / take_screenshot |
| 联网 | web_search（DuckDuckGo，零配置） / web_extract（正文抽取） |
| 浏览器 | browser_open / browser_navigate / browser_snapshot / browser_click / browser_fill（后四个需 `pip install playwright`） / browser_use（AI 自主操作，需 `pip install uiu[browser]`） |
| 微信 | send_wechat（UI 自动化，发送不可撤回，调用前确认） |
| 输入法 | ime_state / ensure_english_ime（键盘输入前先查输入法，防中文 IME 吃字母） |
| 子 agent | delegate_task（内建隔离派发，可限工具白名单） / delegate_batch（并行最多8个） / delegate + list_agents（外部 claude/codex CLI） |
| 视觉桌面 | look / askui_autopilot（需 `pip install uiu[desktop]` + 模型 key） |
| 语音 | speak / listen / voice_state（需 `pip install uiu[voice]`；STT 另需 whisper 相关包） |
| 向量记忆 | add_memory / auto_embed / recall_semantic / memory_state（需 `pip install uiu[rag]`，拖 torch ~2GB） |
| MCP | 配置 `mcp_servers` 后启动自动连接并注入（`mcp_*`），需 `pip install uiu[mcp]` |

> 安全边界：文件读写走路径沙箱（系统目录 + `.env`/密钥文件拒绝，单文件 512KB 上限）；
> `shell_exec` 拦截关机/格式化等危险命令；网关 webhook 支持 `UIU_GATEWAY_TOKEN` 鉴权。

## 自我学习

agent 内建一套"learning loop"，跨会话累积知识：

| 工具 | 干嘛 | 触发时机 |
|---|---|---|
| `memory_add` | 追加一条记忆（带时间戳） | 用户透露持久偏好/事实时主动记 |
| `memory_recall` | 读回长期记忆（含用量表） | 需要跨会话知识时 |
| `memory_replace` | 更新已有记忆 | 信息过时 / 记忆库超预算需合并 |
| `memory_remove` | 删除某条记忆 | 记忆作废 |
| `skill_create` | 把成功方法沉淀成 SKILL.md | 发现可复用流程时 |
| `skill_improve` | 改进已有技能（追加使用记录） | 发现更优做法时 |

- **记忆有界（3000 字符）**：system prompt 带用量表；超 80% 时 `memory_add` 拒绝写入，
  先 `memory_recall` 看全量 + `memory_replace` 合并同类——记忆永远是精炼的 curated 文件，不会无限膨胀。
- **会话检索**：`session_search` / `/search` 在已保存会话里做免费关键词检索（含上下文），跨会话回忆不花 token。
- **压缩前记忆落盘**：`/compact` 把旧轮 LLM 摘要时顺带提炼 `[MEMORY]` 段写入记忆库，旧轮存档为 `auto-compact-*` 会话。
- **周期 nudge**：每 5 轮对话自动提示 agent"这段有什么值得沉淀的"
- **频率感知建议（Hermes /suggestions usage 来源）**：回放 ≥3 次的宏、会话里重复出现的请求主题，
  由 `/suggestions` 建议自动化（宏→定时任务、主题→沉淀宏/skill），accept/dismiss 人工确认，绝不自动创建
- **跨会话**：记忆和技能都落盘在 workspace，下次启动还在
- 写进了 SOUL.md 人设：agent 知道该主动学，不用你提醒

## 安装

```bash
pip install uiu            # Python ≥3.10 直接装（Windows 主推）
uiu                        # 第一次运行自动引导：选模型 → 填 key → 进全屏聊天界面
```

也可以不装全局直接体验：`npx uiu-agent`（自动携带 Python 运行时；本轮以 PyPI 主路径为准）。

> v1.0 起：首次运行不再需要手动 `uiu init` / `uiu config`——
> `uiu` 会自动初始化 workspace（默认 `~/.uiu/workspace`）、弹欢迎向导帮你配好模型，
> 并通过连通性测试后才进入对话。旧工作流（`uiu init` / `uiu config` / `uiu model`）仍完全可用。

## 从源码安装（开发）

```powershell
git clone https://github.com/GameSheep/uiu-agent.git
cd uiu-agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .                    # 仅核心依赖
pip install -e ".[all]"             # 含重依赖（CV/浏览器/RAG/语音/MCP/全渠道）
```

## 快速上手

```powershell
pip install uiu           # ① 安装
uiu                       # ② 首次运行：欢迎向导自动配置模型（DeepSeek/OpenAI/本地 Ollama…）
                          #    配好后自动进入全屏 TUI

# 已有配置的日常用法
uiu init                                        # 手动初始化 workspace（可选）
uiu config --api-key sk-xxx                     # 手动写 API key（可选）
uiu model --set-model deepseek-chat            # 手动换模型
              --set-base-url https://api.deepseek.com/v1
uiu show                                        # 看当前配置（含 tui 主题与配色覆盖）
uiu                                             # 进全屏 TUI 开聊（--no-tui 用经典 REPL）
```

**TUI 常用键**：`Enter` 发送 · `Shift+Enter` 换行 · `Ctrl+N` 新会话 · `Ctrl+E` 命令面板 · `F1` 帮助

## 完整 CLI 参考

### 给脚本用：`--json`

任何支持的子命令都可以加 `--json`（放在 `uiu` 之后或子命令之后都行）。约定：**stdout 只有一个
JSON 文档**，进度与提示一律走 stderr，退出码语义不变。

```bash
uiu --json sessions usage | jq .data.count
uiu --json doctor --lint  | jq '.data.findings[] | select(.severity=="error")'
uiu --json trash --restore <id> ; echo "rc=$?"
```

```json
{"ok": true, "command": "sessions.usage", "data": {"count": 12, "bytes": 84213}}
{"ok": false, "command": "trash.restore", "error": "回收站里没有 xxx"}
```

长任务（`publish` / `update`）会逐步给出「在做什么 + 耗时」，不需要盯着黑屏。

### 默认行为
```
uiu                          # 不带参数 → 进全屏 TUI（textual；--no-tui 回退经典 REPL）
```

### `init`
第一次跑：创建 `workspace/` + `.env` 模板 + 必要目录。
```
uiu init
```

### `show`
打印当前生效的配置（model + channels + secrets 状态）：
```
uiu show
```

### `doctor`
诊断并修复 uiu 配置问题（OpenClaw doctor 风格；uiu 起不来时先跑它）：
```
uiu doctor                    # 诊断并列出问题 + 修复提示
uiu doctor --lint             # 只读检查（不改任何东西），有 error 返回 1
uiu doctor --fix              # 逐项确认后自动修复
uiu doctor --fix --yes        # 全自动修复可修项
```

检查项覆盖：Python 版本 / PyYAML、workspace 完整性（人设文件）、config.yaml 可解析性与结构、
api_mode 合法性、API key 是否存在（自动识别 ollama 等本地 provider 免 key）、
.env 缺失与坏行、channel token 缺失、可选依赖（MCP 等）缺失、**TUI 主题与自定义配色合法性**。
可自动修复：补全 workspace 文件、重置缺失/损坏的 config.yaml（坏文件先备份 `.bak`）、
纠正非法 api_mode、创建 .env 模板、**重置非法 `tui.theme`、删除非法/未知的 `tui.colors` 色位**
——每项修复后自动重扫确认。

### `model`
交互式切换模型（Hermes 风格）：
```
uiu model                          # 进入交互向导：选 provider → 选模型 → 填 key → 测试连接
```
内置 9 个 provider 预设：OpenAI / DeepSeek / Moonshot(Kimi) / Qwen / Ollama(本地) / vLLM(本地) / OpenRouter / SiliconFlow / 自定义。
也可以非交互设置：
```
uiu model --set-model deepseek-chat
uiu model --set-base-url https://api.moonshot.cn/v1
uiu model --set-api-key-env MOONSHOT_API_KEY
uiu model --set-api-key sk-xxx     # 写入当前 api_key_env 到 .env
uiu model --set-temperature 0.3
uiu model --set-max-tokens 8192
```

### `config`
管理 secrets（写入 `workspace/.env`）：
```
uiu config --api-key sk-xxx                      # 写到 model.api_key_env 那把 key
uiu config --set-secret TELEGRAM_BOT_TOKEN=...   # 任意 key=value
uiu config --list                                # 列出所有 secret（默认打码）
uiu config --list --show-values                  # 明文列出
uiu config --unset-secret TELEGRAM_BOT_TOKEN
uiu config --agent-name 小刃                     # 改 agent 显示名（TUI 顶栏/状态条即时生效）
uiu config --theme uiu-neon                     # 设 TUI 主题（写进 config.yaml 的 tui.theme）
uiu config --color primary=#F2A93B              # 覆盖单个色位（写进 tui.colors，留空则清除该位）
```

### `skills`
```
uiu skills list                                  # 列出已加载 skill
uiu skills search <query>                        # 在 GitHub 搜 skill
uiu skills inspect <owner/repo | url>            # 预览不安装
uiu skills install <owner/repo | github-url>     # 安装（装完即用）
uiu skills install <...> --force                 # 覆盖已存在
uiu skills add my_skill                          # 按模板新建
uiu skills edit my_skill                         # 用 $EDITOR 打开
uiu skills reload                                # 重载磁盘上的 skills
uiu skills path                                  # 打印 skills 目录
```

**安装 skill（从 GitHub）：**
```bash
# 从知名 skill 仓库装（比如 openai/skills）
uiu skills install openai/skills
uiu skills install https://github.com/openai/skills

# 装特定子目录的技能
uiu skills install https://github.com/owner/repo/tree/main/skills/foo

# 直接装一个 SKILL.md URL
uiu skills install https://raw.githubusercontent.com/.../SKILL.md
```
安装到 `workspace/skills/<name>/`，重启 uiu（或 `/skills reload`）立即生效，agent 马上能用。

### `channel`
管理外部渠道（Hermes 平台 adapter 风格）。内置 adapter：**telegram / feishu(飞书) / wecom(企业微信) / dingtalk(钉钉) / discord / slack**。

**Telegram / Discord**（长连接，无需公网）：
```
uiu channel add tg-main --type telegram
uiu config --set-secret TELEGRAM_BOT_TOKEN=<BotFather 给的 token>
uiu channel test tg-main                         # 调 getMe 验证

uiu channel add dc-main --type discord
uiu config --set-secret DISCORD_BOT_TOKEN=<Discord Developer Portal token>
```

**钉钉**（Stream 模式长连接，无需公网）：
```
uiu channel add dt-main --type dingtalk \
  -o client_id=dingxxx -o client_secret=xxx
uiu channel test dt-main
```

**Slack**（Socket Mode 长连接，无需公网）：
```
uiu channel add sl-main --type slack -o app_token=xapp-...
uiu config --set-secret SLACK_BOT_TOKEN=xoxb-...
```

**飞书**（webhook，需公网回调）：
```
uiu channel add fs-main --type feishu \
  -o app_id=cli_xxx -o app_secret=xxx [-o verify_token=xxx]
uiu channel test fs-main
```

**企业微信**（webhook，需公网回调；自建应用消息默认走官方 AES 加密回调）：
```
uiu channel add wc-main --type wecom \
  -o corpid=wwxxx -o corpsecret=xxx -o agentid=1000002 \
  -o token=<回调 Token> -o aes_key=<回调 EncodingAESKey>   # 配置后启用官方验签+AES 解密
uiu channel test wc-main
```
> 配置 `token` + `aes_key`（在企微后台"接收消息"设置里）后，`/wecom` 回调强制走官方
> 验签与 AES 解密，伪造消息会被拒绝；不配置则退回明文转发（需网关 token 保护）。

通用操作：
```
uiu channel list                    # 列出所有 channel
uiu channel disable <name>          # 临时关掉
uiu channel enable <name>
uiu channel remove <name>
```

### `serve`（gateway——核心）
启动网关：所有 enabled 的 channel 并行跑，消息进来 → agent 回复。
```
uiu serve                # 默认 webhook 端口 8765
uiu serve --port 9000
```

- **Telegram**：长轮询 `getUpdates`，无需公网
- **飞书 / 企微 / WhatsApp**：起本地 HTTP server（`/feishu`、`/wecom`、`/whatsapp`），需要把平台的回调地址指向这里（用内网穿透如 ngrok/frp 暴露公网）
- **通用 webhook**：任意系统 `POST /generic/<channel名>` 即变消息源（`chat_field`/`text_field` 配字段路径，`secret` 配校验）
- **api_server**：`POST /api/send {chat_id, text, channel?}` 编程外发，`GET /api/channels` 看在线通道（设 `UIU_GATEWAY_TOKEN` 后需带 `X-Gateway-Token` 头）
- 每个 chat_id 独立会话上下文（落盘 `sessions/gw-<chat>.json`，重启不丢），支持多人群聊/私聊
- 网关内 slash 命令与 TUI 同款（`/cron`、`/sessions` 等直接对聊天发）
- cron tick：serve 内每 60s 自动跑到期定时任务，结果进 `cron/output/`

**加 channel（9 种）：telegram / feishu / wecom / dingtalk / discord / slack / whatsapp / email / webhook**，通用操作同下。WhatsApp 需 `-o phone_id=` + `WHATSAPP_TOKEN`；邮箱需 `-o imap= -o smtp= -o user=` + `EMAIL_PASSWORD`（建议应用专用密码）。

**Channel 插件**：放 `~/.uiu/channels/<name>/__init__.py`（继承 BaseChannelAdapter，实现 check/start/send），`uiu serve` 自动发现。改平台不用改核心代码。

### `update`
```powershell
uiu update self                                  # 安全更新
uiu update skills                                # 同步默认 skills 到 workspace
```

**安全更新机制：**
更新前自动隔离验证（语法检查 + 模块导入测试），验证通过才真正安装。出问题可一键回滚。

### `publish`
```
uiu publish                          # 构建 + 上传到 PyPI（需要 PYPI_TOKEN）
uiu publish --test                   # 构建 + 上传到 TestPyPI 试水
```

### `plugins`（provider 插件，Hermes 风格）
```
uiu plugins list                     # 列出已安装的用户 provider 插件
uiu plugins new my-provider          # 从模板脚手架一个新 provider 插件
uiu plugins path                     # 打印插件目录（~/.uiu/plugins/model-providers/）
```

**插件机制（对齐 Hermes）：**
- 插件放 `~/.uiu/plugins/model-providers/<name>/`，含 `__init__.py`（调 `register_provider(profile)`）+ `plugin.yaml`（manifest）
- 首次调用时懒发现（`uiu model` / `uiu show` 触发）
- **用户插件覆盖内置**（last-writer-wins）——改内置 provider 不用动代码
- 加 provider 三步：`uiu plugins new my-provider` → 编辑 `__init__.py` 的 base_url/key 名/模型列表 → `uiu model` 里就能选

### `version`
```
uiu version
```

## 全屏 TUI

`uiu` 默认进入 **textual 全屏聊天应用**，不是脚本式 REPL：

```
◆ uiu  小刃                                             deepseek-chat
C:\Users\you\.uiu\workspace      123 工具 · 0 技能 · v1.0.0 · default
──────────────────────────────────────────────────────────────────────
╭──────────────────────────────────────────────────────────────────╮
│ ◆ uiu  小刃                              ·  已就绪  ·  123 工具  │
│ 你的个人 IP agent —— 常驻在这台电脑上，替你动手。                 │
│ ⚙ 123 工具  ◉ 屏幕 OCR  ⌘ 桌面控制  ⏱ 宏 / 定时  ✉ 消息渠道      │
╰──────────────────────────────────────────────────────────────────╯

从这些开始
╭────────────────────────────╮ ╭────────────────────────────╮
│ › 看看磁盘和内存占用        │ │ › 列出我有哪些技能          │
╰────────────────────────────╯ ╰────────────────────────────╯

╭──────────────────────────────────────────────────────────────────╮
│ ❯ 输入消息…                                                      │
╰──────────────────────────────────────────────────────────────────╯
↵ 发送 · Shift+↵ 换行 · / 命令 · Ctrl+E 面板 · F1 帮助          12 字
──────────────────────────────────────────────────────────────────────
○ idle   小刃 · deepseek-chat   turns 2   ctx ██████░░░░░░ 48%   tools 123 · skills 0   14:32
```

- **品牌化首屏**：空态是一张产品卡（品牌字标 + 一句话定位 + 能力徽章）和「从这些开始」建议卡，点一下直接开聊；
  有已存会话时，首屏顶部多一张 **继续上次会话** 卡片（会话名 + 轮数 + 上次时间 + 最后那句提问，一键载入）。
- **推理过程可折叠**：模型的思考块显示为 `✻ 思考过程  N 字 · 0.4s`，短思考展开、长思考（>160 字）
  结束后自动收起，点一下展开/收起——长推理不再刷屏。
- **消息区**：每条消息带角色字形、名字与时间戳（回答流式期间显示 `正在生成…` 与行尾 `▍` 光标），
  左侧一条角色色竖线（你=蓝，agent=青，错误=红）。
  agent 回复以 markdown **流式渲染**（代码/列表/表格实时高亮），流式时行尾有 `▍` 光标。
- **工具调用**：调用发出即出现一行 `⚙ 工具名 ⠋ 运行中…`（spinner 实时转），
  返回后变成 `⚙ 工具名 ✓ 摘要 …… 0.4s`，点一下展开完整入参与返回。
- **命令输出折叠**：`/help`、`/tools` 这类长输出不再糊满屏幕，而是折成
  `❯ /help  21 行  [点击展开]`，展开后是等宽对齐的代码块（命令输出本来就该按原文排）。
- **可点的行会「发光」**：工具行 / 思考块 / 可折叠的命令输出都有手型光标与悬停底色，
  不用猜哪里能点；窗口标题也会跟着会话走（`uiu — 会话名 · 模型`）。
- **Markdown 排版**：代码块有独立底纹与左侧色条、行内码有底色、标题分级着色、
  引用带竖线、表格带网格线——回复里的结构化内容直接可读。
- **主题**：内置 4 套配色（`uiu-dark` / `uiu-mono` / `uiu-neon` / `uiu-solar`），
  `Ctrl+T` 打开主题选择器，↑↓ 实时预览、Enter 应用、Esc 还原；选择会写进
  `workspace/config.yaml` 的 `tui.theme`，下次启动自动沿用。
- **自定义配色**：`config.yaml` 里 `tui.colors` 可覆盖任意色位（其余继承 `tui.theme`），
  例如 `tui: {theme: uiu-dark, colors: {primary: "#F2A93B", background: "#120F0C"}}` ——
  覆盖后生效的是派生主题 `uiu-custom`。
- **会话切换器**（`Ctrl+X` 或 `/sessions`）：列出已存会话（轮数 + 当前标记），Enter 载入、
  `d` 删除；载入后消息区会把历史对话重新渲染出来。
- **会话用量面板**（`Ctrl+U` 或 `/usage`）：模型 / 会话 / 轮数 / 上下文占用条 / token 估算 /
  消息数 / 工具数 / 已存会话 / 工作区，一屏看完。
- **运行状态面板**（`/status`）：agent / 模型 / base_url / api_mode / **API key 是否就位** /
  渠道启用数 / MCP / 工具·技能 / 当前会话 / 主题 / 版本 / 工作区——排查"为什么没反应"最快的一屏。
- **运行中想走神也看得见**：状态条显示 `⠋ running 3s`（实时计时），输入框提示行同步显示
  `agent 思考中… ⚙ read_file`（当前正在跑的工具名）。
- **输入历史**：输入框里 `↑`/`↓` 翻上一条提问（进入会话时自动带上该会话的历史提问）。
- **对话内检索**（`Ctrl+R`）：浮层里输入关键词过滤当前对话（含折叠的命令输出，显示来源 + 时间 + 摘要，**命中词加粗**），
  Enter 跳到那条消息并高亮闪一下；浮层底部显示 `命中 N 处`，之后用 `F3` / `Shift+F3` 在各处命中之间循环跳转（状态条同步显示进度）。
- **跨会话检索**（`/search <关键词>`）：输入即搜所有已存会话（关键词 AND 匹配，本地毫秒级、不花 token），
  命中项显示会话名 + 角色 + 摘要（命中词加粗）+ 一行上下文；Enter 直接打开那个会话并跳到命中的消息。
- **长文本粘贴折叠**：一次粘贴超过 6 行 / 600 字时，输入框只留 `[粘贴 1 · 24 行 / 320 字]` 占位，
  发送时自动还原全文，右下角字数按展开后计算。
- **窄终端自适应**：宽度 <88 列自动收起侧栏（变宽自动还原），<74 列顶栏收成单行，
  状态条按宽度分档丢时钟 / 会话名 / 计数（<60 列只留模式 + 模型 + 用量），输入区提示行同步缩短；
  首屏能力徽章与建议卡也会按宽度换成 1 列。
- **侧栏**（`Ctrl+S`）：顶部是**最近会话**（最近 3-4 个其他会话，显示相对时间，点一下直接切过去）
  + `全部会话…`，接着是**本次会话**统计（会话名 / 轮数 / 工具数 / 上下文占用），
  再往下是 会话 / 视图 / 信息 三组带快捷键提示的入口。
- **滚上去也不慌**：手动上滚后若又有新内容产出，状态条提示 `↓ 新内容 · Ctrl+End`，
  按 `Ctrl+End` 一键回到底部并恢复自动跟随。
- **长会话不拖沓**：消息区常驻最近 60 条，更早的折叠成顶部一行
  `› 更早的 N 条消息已折叠 · 点击展开（再展开 60 条）`——**每点一次多加载一页**（硬上限 400 条），
  不会一次渲染几百条把界面卡住；新一轮对话时自动回收到常驻窗口。
- **轻提示不脏屏**：复制成功、主题切换这类**瞬时反馈**只出现在状态条（`✓ 已复制上一条回答 · 25 字`，
  3 秒后自动消失），不会往对话里塞气泡；失败时变红并保留更久。
- **复制**：每条回答右上角有 `⧉` 按钮（复制这一条）；`Ctrl+Y` 复制上一条回答；`/copy` 同上，
  `/copy all` 复制整段会话为 Markdown（带会话名、轮数、时间）。剪贴板走 pyperclip，
  失败时回退 PowerShell `Set-Clipboard`，再失败会明确报错而不是静默。
- **导出到文件**：`/export [名字]` 把会话写成 Markdown 落到 `workspace/exports/<名字>.md`
  （空会话会拒绝并提示，不会留下空文件）。
- **主题面板会说明覆盖**：`tui.colors` 生效时，主题选择器底部显示
  `tui.colors 覆盖中：primary #F2A93B  accent #E4572E`，不会再疑惑「为什么选了主题没变色」。
- **状态条**：idle/running/error 状态点（运行时是迷你 spinner + `running 3s` 计时）、模型、轮数、
  上下文用量条（按占用变色 + `=14ktok` 估算）、工具/技能数、会话名与时钟，宽度不够时逐级省略。
- **帮助浮层**（`F1`）：左侧分类导航（快捷键 / 命令 / 工具 / 技能 / 关于），右侧可滚动正文。
- **命令补全**：输入 `/` 弹出浮层面板，命令 + 一行说明，↑↓ 选择、Tab/Enter 确认。
- **多行输入**：`Enter` 发送、`Shift+Enter` 换行；输入区带提示符 `❯`、运行中边框变黄、右下角实时字数。
- **命令面板**（`Ctrl+E`）：不只是 slash 命令——它把**动作**（新会话 / 切换会话 / 切换主题 /
  搜索当前对话 / 会话用量 / 运行状态 / 复制回答 / 导出会话 / 回到底部…）、**最近会话**和全部 **slash 命令**
  放在一起模糊过滤（左侧标 `动作 / 会话 / 命令`，右侧是快捷键或说明），底部显示条目数。
- **快捷键**：`Ctrl+N` 新会话 · `Ctrl+E` 命令面板 · `Ctrl+T` 主题 · `Ctrl+X` 切换会话 ·
  `Ctrl+U` 会话用量 · `Ctrl+S` 侧栏 · `Ctrl+R` 历史搜索 · `Ctrl+L` 清屏 · `F1` 帮助 ·
  `Ctrl+R` 搜索当前对话 · `F3`/`Shift+F3` 逐个命中 · `F2` 状态条 · `↑`/`↓` 翻输入历史 · `Esc` 中断回复。
- **不卡顿**：agent 回合在后台线程跑；**斜杠命令同样不阻塞界面**——`/compact`（要跑 LLM）、
  `/cron run` 这类慢命令在执行期间界面照常滚动/打字，状态条显示 `⠋ running`、输入区提示
  `⚙ /compact 执行中 · 完成后自动返回`（**不谎报 Esc 可中断**），完成后自动复位。等待回复时也可滚动/打字/开命令面板。
- **敏感操作内联确认**：`send_wechat` / `shutdown` / `macro_play` 触发时弹确认框，绝不静默执行。
- 非交互终端（管道/CI）自动回退经典 REPL；显式需要旧界面用 `uiu --no-tui`。

### 界面导览

想看界面长什么样，先翻 **[@docs/tui-tour.md](docs/tui-tour.md)**——每个界面配一张图 + 说明。

图由仓库自带的 headless 预览器生成：用假 client 驱动**真实界面**，不需要模型也不需要网络。

```powershell
python scripts/tui_preview.py                  # 全部状态 → docs/preview/
python scripts/tui_preview.py --only palette   # 只渲染一个状态
```

导出的是 textual 的 256 色降级结果——**布局与排版可信，配色仅供参考**（要核对颜色请直接跑 `uiu`）。

## TUI 内置命令

在 TUI 内（`uiu` 不带参数），slash 命令与网关聊天共用同一注册表：

| 命令 | 干嘛 |
|---|---|
| `/help` | 帮助 |
| `/skills` / `/skills reload` | 列出 / 重载 skill |
| `/tools` | 列出内置工具 |
| `/identity` | 打印 IDENTITY.md |
| `/memory <内容>` | 追加一行到 MEMORY.md（有界：超 3000 字符预算拒绝并提示合并） |
| `/soul <内容>` | 追加一行到 SOUL.md |
| `/save [名]` / `/resume [名]` | 保存 / 恢复会话（退出重进自动恢复 `default`；网关会话自动存） |
| `/sessions` | 列出已保存会话（TUI 里直接打开会话切换浮层） |
| `/search <关键词>` | 跨已存会话检索（TUI 里打开检索浮层：输入即搜、命中词加粗、Enter 打开会话） |
| `/compact` | 压缩旧对话：LLM 摘要 + 提炼 `[MEMORY]` 记忆落盘，旧轮存档 `auto-compact-*` |
| `/suggestions` | 自动化建议：常用宏→定时任务、重复请求→沉淀提示（accept/dismiss 人工确认） |
| `/status` | 状态（TUI 里打开运行状态面板：模型/key/渠道/主题…） |
| `/usage` | 上下文用量（TUI 里打开会话用量面板） |
| `/new` | 新会话（旧的自动存快照） |
| `/cron …` | 定时任务（list/add/rm/on/off/run/tick） |
| `/clear` | 清空对话上下文 |
| `/theme` | 打开主题选择器（同 `Ctrl+T`） |
| `/quit` `/exit` | 退出 |

输入框下方常驻状态条：`○ idle  模型  turns:N  ctx ███░░░ %  tools:N · skills:M  时钟`，
idle/running/error 变色（running 时状态点是滚动的 spinner）；回答 token 级流式输出（卡顿时立刻能看见）；
工具调用显示为单行 `⚙ 名 ✓ 耗时 摘要`（失败红色 `✗`），点一下展开完整入参与返回。
非 UTF-8 终端（或管道）符号自动降级 ASCII，不会乱码崩溃。

### `cron`
```
uiu cron add 早报 "30m" "搜今天的 AI 新闻并摘要"   # 间隔：30m/2h/1d
uiu cron add 晨会 "daily 09:00" "汇总微信未读"      # 每天 09:00
uiu cron add x "0 9 * * 1-5" "任务"                # 完整 5 段 cron（分 时 日 月 周）
                                                   # 支持 */n、范围、列表：*/15、9-11、1-5
uiu cron add once "once 2026-09-05T10:00:00" "任务"  # 单次
uiu cron add 备份 "2h" "xcopy ..." --shell         # shell 任务：跑命令零 token（不调 agent）
uiu cron list / run <名> / tick / on|off|remove <名>
```

输出进 `workspace/cron/output/<id>/<时间>.md`；`uiu serve` 每 60s 自动 tick。
网关/TUI 里 `/cron add 备份 2h "!xcopy ..."` 等价（任务以 `!` 开头即 shell 任务）。

### `sessions`

```
uiu sessions list              # 已保存会话（含网关的 gw-*）
uiu sessions show <名>         # 看最近 20 轮
uiu sessions search <关键词>   # 跨会话关键词检索（免费秒回）
uiu sessions remove <名>
```

### `sessions`

```bash
uiu sessions list                              # 含每个会话的大小与总量
uiu sessions usage                             # 数量 / 占用 / 最大的几个
uiu sessions prune --keep 50 --yes             # 只留最新 50 个（裁剪进回收站，可 uiu trash 恢复）
uiu sessions prune --days 30 --dry-run         # 先看会删哪些（30 天前的）
uiu sessions show <名> · search <关键词> · remove <名>
```

保留策略写在 `config.yaml`：`sessions_keep`（默认 200）、`sessions_max_age_days`、
`sessions_auto_prune`（**默认 false**：daemon 只在超限时告警，绝不擅自删你的会话）。

### `doctor`

自检 + 自动修复。可选能力栈缺失（浏览器 / 桌面 UIA / 语音 / RAG）以 **info** 列出并给出安装命令，
但**默认不会替你装**（那些包动辄上百 MB）：

```bash
uiu doctor --lint                        # 只看不改（rc=1 仅当有 error 级问题）
uiu doctor --fix                         # 逐项确认后修复（不碰 pip）
uiu doctor --fix --yes                   # 全部自动修
uiu doctor --fix --yes --install-deps    # 连缺失的可选依赖也一起装
```

### `trash`（回收站 / 撤销）

删除会话、宏、渠道、定时任务**都是可撤销的**：它们先进回收站，默认保留 7 天（daemon 每天清理）。
TUI 里删完按 **Ctrl+Z** 也能立刻找回。

```bash
uiu trash                                  # 列出回收站条目
uiu trash --restore 20260917-120000-session-doome-1a2b
uiu trash --purge --days 7                 # 清理超过 7 天的条目
uiu sessions remove <名>                   # 删会话（进回收站）
uiu macro remove <名>                      # 删宏（进回收站）
```

### `audit`

谁在什么时候用什么参数做了什么、用户确认与否——每次工具执行都会留一条 append-only 记录
（密钥字段自动脱敏）。

```bash
uiu audit                # 最近 30 条
uiu audit --tail 200     # 最近 200 条
uiu audit --json         # 原始 JSONL（便于接日志系统）
```

落盘在 `<workspace>/audit/uiu-audit.jsonl`，超过 5MB 自动滚动。

### `backup` / `restore`

用户数据的兜底：配置、会话、记忆、技能、定时任务打包成一个 zip；恢复前会自动留一份快照，
所以**恢复本身也是可撤销的**。

```bash
uiu backup                     # → <workspace>/backups/uiu-backup-<时间戳>.zip（滚动保留 7 份）
uiu backup --list              # 看已有备份
uiu backup --to D:\uiu-bak     # 备份到别处（不影响 workspace 内的滚动保留）
uiu restore <zip>              # 覆盖前会确认，并先做一份 pre-restore 快照
uiu restore <zip> --yes        # 跳过确认（脚本/自动化用）
```

备份内容：`config.yaml`、`.env`、`SOUL/IDENTITY/USER/MEMORY.md`、`sessions/`、`cron/`、`skills/`；
**不含** `logs/`、`cron/output/`、`backups/`、锁与临时文件。
注意 `.env` 里有 API key，备份文件请按密钥文件保管。`uiu daemon` 起手会做每日自动备份（24h 一次）。

## 怎么变成"你的 agent"

1. **改 SOUL.md**：写你的价值观、口头禅、不喜欢的东西。这是灵魂。
2. **改 IDENTITY.md**：给它起名、定位、调性。
3. **填 USER.md**：告诉它你是谁。
4. **加 skill**：`workspace/skills/<name>/SKILL.md`
   - 简单 skill：声明 `exec: <内置名>`（如 `exec: echo`），再用 ```tool_schema 块声明参数。
   - 复杂 skill：在 `src/uiu/skills_runtime.py` 里注册 Python 函数当 builtin。
5. **改 agent 名字**：两处可改（TUI 顶栏/状态条/`/status` 即时显示）——
   `workspace/IDENTITY.md` 里 `## 名字` 一行，或 `uiu config --agent-name 小刃`（config 优先）。
6. **加 channel**：`uiu channel add <name> --type telegram`
   然后 `uiu config --set-secret TELEGRAM_BOT_TOKEN=<botfather 给你的 token>`

## 配置存储

| 文件 | 内容 | 入 git？ |
|---|---|---|
| `workspace/config.yaml` | 模型参数、channel 列表、agent_name | ✅ |
| `workspace/.env` | API key / bot token 等秘密 | ❌ 加到 .gitignore |
| `workspace/SOUL.md` 等 | 人设 / 记忆 / skill 定义 | ✅ |

秘密走 `*.env`，配置走 `*.yaml`——这样你可以把整个 workspace push 到 GitHub 不泄露 token。

## 目录结构

```
uiu/
├── pyproject.toml
├── README.md
├── DEVELOPMENT.md               # 完成度评审 + 对标差距 + 路线图
├── cli_smoke.py                  # 离线冒烟（CI 同款）
├── .env.example
├── src/uiu/                       # 核心代码
│   ├── main.py                        # CLI 入口
│   ├── commands.py                    # 子命令实现
│   ├── config.py                      # 配置读写
│   ├── channels*.py                   # channel adapter
│   ├── wecom_crypto.py                # 企微回调 AES 解密/验签
│   ├── gateway.py                     # serve 网关
│   ├── workspace.py                   # SOUL/skills/memory 加载
│   ├── tools.py                       # 工具注册表
│   ├── agent.py                       # 对话 + 工具调用循环
│   ├── tui.py                         # 经典 REPL（降级路径，--no-tui）
│   ├── app/                           # textual 全屏 TUI（消息区/输入区/侧栏/状态条）
│   │   ├── app.py                     # UiuApp 主应用
│   │   ├── widgets/                   # ChatView / Composer / SideBar / StatusBar
│   └── _default_workspace/            # init 模板
├── tests/                             # pytest（200+ 用例）
└── workspace/                         # 你的 IP 在这里
    ├── config.yaml
    ├── .env
    ├── SOUL.md
    ├── IDENTITY.md
    ├── USER.md
    ├── MEMORY.md
    └── skills/
```

## 验证

```powershell
# 冒烟测试（不需要真 LLM/网络）
.\.venv\Scripts\python.exe cli_smoke.py

# 单元测试（含 textual 全屏 TUI 的离线 pilot 测试）
.\.venv\Scripts\python.exe -m pytest tests/ -q

# Windows 安装态验收（构建 wheel → 全新 venv → version/init/doctor/show/TUI 冒烟）
powershell -ExecutionPolicy Bypass -File scripts/verify_windows_install.ps1
```
