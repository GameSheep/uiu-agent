# uiu

> 一个**最小可跑**的个人 IP agent 骨架。借鉴 Hermes Agent 的 SOUL/skills/memory 模式，但砍到只剩核心。

## 它能做什么

- 跟你多轮对话，记住上下文（同一会话内）。
- 自动调用 3 个内置工具：`shell_exec` / `read_file` / `write_file`。
- 自动调用 `workspace/skills/*/SKILL.md` 里声明的 skill。
- 你的"人设"写在 `workspace/SOUL.md` 里——改它，agent 就变样。
- 长记忆写在 `workspace/MEMORY.md`——对话里 `/memory <note>` 一键追加。
- **完整 CLI**：配置模型、添加 skill、加 channel（目前支持 Telegram）、更新代码。
- **可发布到 PyPI**：`uiu publish` 一行构建 + 上传，全世界 `pip install uiu`。

## 安装（发布后）

```bash
pip install uiu        # 安装
uiu init               # 首次初始化 workspace
uiu                    # 开聊
```

或者不装全局，直接跑：
```bash
pipx run uiu
```

## 发布到 PyPI（作者用）

1. 注册 [PyPI 账号](https://pypi.org/account/register/)
2. 到 [API tokens](https://pypi.org/manage/account/token/) 建一个 token（scope 选 "Entire account"）
3. 把 token 存环境变量：
   ```powershell
   $env:PYPI_TOKEN = "pypi-xxxxx"
   ```
4. 发布：
   ```powershell
   uiu publish              # 正式发布到 PyPI
   uiu publish --test       # 先发 TestPyPI 试水
   ```
5. 验证：
   ```powershell
   pip install uiu
   uiu version
   ```

> 发布前记得把 `pyproject.toml` 里的 `version` 升版本（每次发布必须比上次大）。
> 发布后 1-2 分钟生效。

## 安装（本地开发）

```powershell
cd E:\Code\Personal\agent\my-agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
```

## 快速上手

```powershell
uiu init                                          # 建 workspace
uiu config --api-key sk-xxx                       # 写 API key
uiu model --set-model deepseek-chat \             # 换模型（DeepSeek/Moonshot/Ollama 都行）
              --set-base-url https://api.deepseek.com/v1
uiu show                                          # 看当前配置
uiu                                               # 进 TUI 开聊
```

## 完整 CLI 参考

### 默认行为
```
uiu                          # 不带参数 → 进 TUI REPL
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
```

### `skills`
管理 skill：
```
uiu skills list                                  # 列出已加载 skill
uiu skills add my_skill                          # 按模板新建
uiu skills edit my_skill                         # 用 $EDITOR 打开
uiu skills path                                  # 打印 skills 目录
```

### `channel`
管理外部渠道（Hermes 平台 adapter 风格）。内置 adapter：**telegram / feishu(飞书) / wecom(企业微信)**。

**Telegram：**
```
uiu channel add tg-main --type telegram
uiu config --set-secret TELEGRAM_BOT_TOKEN=<BotFather 给的 token>
uiu channel test tg-main                         # 调 getMe 验证
```

**飞书：**
```
uiu channel add fs-main --type feishu \
  -o app_id=cli_xxx -o app_secret=xxx [-o verify_token=xxx]
uiu channel test fs-main
```

**企业微信：**
```
uiu channel add wc-main --type wecom \
  -o corpid=wwxxx -o corpsecret=xxx -o agentid=1000002
uiu channel test wc-main
```

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
- **飞书 / 企微**：起本地 HTTP server（`http://0.0.0.0:8765/feishu`、`/wecom`），需要把平台的回调地址指向这里（用内网穿透如 ngrok/frp 暴露公网）
- 每个 chat_id 独立会话上下文，支持多人群聊/私聊
- 按 channel 自动路由回复（消息从哪个平台来，回复回哪去）

**Channel 插件**：放 `~/.uiu/channels/<name>/__init__.py`（继承 BaseChannelAdapter，实现 check/start/send），`uiu serve` 自动发现。改平台不用改核心代码。

### `update`
```
uiu update self                                  # git pull（如有 remote）+ 重装，幂等
uiu update self --no-pull                        # 只重装，不拉远程
uiu update skills                                # 同步默认 skills 到 workspace
```

**更新流程（推荐）：** 改完代码 → `git add -A && git commit -m "..."` → `uiu update self`。
git 本身就是回滚手段（`git log` / `git revert`），update 永不碰你的 workspace 人设。

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

## TUI 内置命令

在 TUI 内（`uiu` 不带参数）：

| 命令 | 干嘛 |
|---|---|
| `/help` | 帮助 |
| `/skills` | 列出已加载的 skill |
| `/tools` | 列出内置工具 |
| `/identity` | 打印 IDENTITY.md |
| `/memory <内容>` | 追加一行到 MEMORY.md |
| `/clear` | 清空对话上下文 |
| `/quit` `/exit` | 退出 |

## 怎么变成"你的 agent"

1. **改 SOUL.md**：写你的价值观、口头禅、不喜欢的东西。这是灵魂。
2. **改 IDENTITY.md**：给它起名、定位、调性。
3. **填 USER.md**：告诉它你是谁。
4. **加 skill**：`workspace/skills/<name>/SKILL.md`
   - 简单 skill：声明 `exec: <内置名>`（如 `exec: echo`），再用 ```tool_schema 块声明参数。
   - 复杂 skill：在 `src/uiu/skills_runtime.py` 里注册 Python 函数当 builtin。
5. **加 channel**：`uiu channel add <name> --type telegram`
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
├── .env.example
├── src/uiu/                       # 代码（~1100 行）
│   ├── main.py                        # CLI 入口（argparse subparsers）
│   ├── commands.py                    # 8 个子命令实现
│   ├── config.py                      # config.yaml + .env 读写
│   ├── channels.py                    # channel adapter（Telegram getMe）
│   ├── workspace.py                   # SOUL/skills/memory 加载
│   ├── llm.py                         # OpenAI 兼容客户端
│   ├── tools.py                       # 3 个内置工具 + registry
│   ├── skills_runtime.py              # skill 执行器
│   ├── agent.py                       # 对话 + 工具调用循环
│   ├── tui.py                         # Rich + prompt_toolkit
│   └── _default_skills/say_hello/     # update skills 同步的内容
│       └── SKILL.md
└── workspace/                         # 你的 IP 在这里
    ├── config.yaml
    ├── .env
    ├── SOUL.md
    ├── IDENTITY.md
    ├── USER.md
    ├── MEMORY.md
    └── skills/
        ├── _default/say_hello/        # update skills 之后会出现在这
        └── echo/                      # 你自己加的 skill
```

## 和 Hermes 的关系

Hermes Agent 全量 10000+ 文件、cli.py 单文件 1MB。本骨架是其"工作区模式"的精简：
- ✅ 保留了：SOUL/IDENTITY/USER/MEMORY 分层、SKILL.md 渐进披露、内置工具 + 插件工具并行、对话循环。
- ❌ 砍掉了：多平台 gateway、cron、subagent 派发、训练数据生成、ACP/MCP 协议、桌面应用、UI 前端。

需要哪块再补，不预加载。

## 验证

仓库自带 `cli_smoke.py`（22 个测试用例覆盖全部子命令，不需要真 LLM/网络）：
```
.venv\Scripts\python.exe cli_smoke.py
# === 22/22 passed ===
```