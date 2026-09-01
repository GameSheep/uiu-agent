# my-agent

> 一个**最小可跑**的个人 IP agent 骨架。借鉴 Hermes Agent 的 SOUL/skills/memory 模式，但砍到只剩核心。

## 它能做什么

- 跟你多轮对话，记住上下文（同一会话内）。
- 自动调用 3 个内置工具：`shell_exec` / `read_file` / `write_file`。
- 自动调用 `workspace/skills/*/SKILL.md` 里声明的 skill。
- 你的"人设"写在 `workspace/SOUL.md` 里——改它，agent 就变样。
- 长记忆写在 `workspace/MEMORY.md`——对话里 `/memory <note>` 一键追加。
- **完整 CLI**：配置模型、添加 skill、加 channel（目前支持 Telegram）、更新代码。

## 安装

```powershell
cd E:\Code\Personal\agent\my-agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
```

## 快速上手

```powershell
my-agent init                                          # 建 workspace
my-agent config --api-key sk-xxx                       # 写 API key
my-agent model --set-model deepseek-chat \             # 换模型（DeepSeek/Moonshot/Ollama 都行）
              --set-base-url https://api.deepseek.com/v1
my-agent show                                          # 看当前配置
my-agent                                               # 进 TUI 开聊
```

## 完整 CLI 参考

### 默认行为
```
my-agent                          # 不带参数 → 进 TUI REPL
```

### `init`
第一次跑：创建 `workspace/` + `.env` 模板 + 必要目录。
```
my-agent init
```

### `show`
打印当前生效的配置（model + channels + secrets 状态）：
```
my-agent show
```

### `model`
查看 / 修改模型配置（写入 `workspace/config.yaml`）：
```
my-agent model
my-agent model --set-model deepseek-chat
my-agent model --set-base-url https://api.moonshot.cn/v1
my-agent model --set-api-key-env MOONSHOT_API_KEY
my-agent model --set-temperature 0.3
my-agent model --set-max-tokens 8192
```

### `config`
管理 secrets（写入 `workspace/.env`）：
```
my-agent config --api-key sk-xxx                      # 写到 model.api_key_env 那把 key
my-agent config --set-secret TELEGRAM_BOT_TOKEN=...   # 任意 key=value
my-agent config --list                                # 列出所有 secret（默认打码）
my-agent config --list --show-values                  # 明文列出
my-agent config --unset-secret TELEGRAM_BOT_TOKEN
```

### `skills`
管理 skill：
```
my-agent skills list                                  # 列出已加载 skill
my-agent skills add my_skill                          # 按模板新建
my-agent skills edit my_skill                         # 用 $EDITOR 打开
my-agent skills path                                  # 打印 skills 目录
```

### `channel`
管理外部渠道。目前 adapter：**telegram**（用官方 Bot API 做 token 校验）。
```
my-agent channel list
my-agent channel add tg-main --type telegram          # 会自动用 TELEGRAM_BOT_TOKEN
my-agent channel add tg-main --type telegram --secret-env MY_TG_TOKEN
my-agent channel add tg-main --type telegram -o polling=true -o timeout=30
my-agent channel test tg-main                         # 调 getMe 验证 token
my-agent channel disable tg-main                      # 临时关掉
my-agent channel enable tg-main
my-agent channel remove tg-main
```

接 Telegram 的真正 gateway（轮询消息、转给 agent）**没实现**，只有 token 校验。
后续如果要长期监听 Telegram 消息，需要在 `channels.py` 加 gateway 函数 + 一个 `serve` 命令。

### `update`
```
my-agent update self                                  # 重装自己（pip install -e .）
my-agent update skills                                # 同步默认 skills 到 workspace
```

### `version`
```
my-agent version
```

## TUI 内置命令

在 TUI 内（`my-agent` 不带参数）：

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
   - 复杂 skill：在 `src/myagent/skills_runtime.py` 里注册 Python 函数当 builtin。
5. **加 channel**：`my-agent channel add <name> --type telegram`
   然后 `my-agent config --set-secret TELEGRAM_BOT_TOKEN=<botfather 给你的 token>`

## 配置存储

| 文件 | 内容 | 入 git？ |
|---|---|---|
| `workspace/config.yaml` | 模型参数、channel 列表、agent_name | ✅ |
| `workspace/.env` | API key / bot token 等秘密 | ❌ 加到 .gitignore |
| `workspace/SOUL.md` 等 | 人设 / 记忆 / skill 定义 | ✅ |

秘密走 `*.env`，配置走 `*.yaml`——这样你可以把整个 workspace push 到 GitHub 不泄露 token。

## 目录结构

```
my-agent/
├── pyproject.toml
├── README.md
├── .env.example
├── src/myagent/                       # 代码（~1100 行）
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