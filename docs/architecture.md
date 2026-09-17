# 架构说明

> 面向「要改这个仓库的人」。数字为 2026-09-17 实测：`src` 109 个模块 / 26,443 行（其中 `app/` 之外的
> 核心 96 模块 / 21,640 行），`tests` 65 文件 / 8,071 行，123 个内置工具，20 个顶层 CLI 命令。

## 分层

```
入口层     main.py（argparse + 分发）         commands.py（各子命令实现）
                │
运行时     app/（Textual TUI）   gateway.py（渠道网关）   daemon.py（后台常驻）   cron.py（定时任务）
                │                        │                      │
            agent.py  ── run_turn()：把消息喂模型、执行工具、回填结果
                │
能力层     tools.py（注册表 + 唯一执行入口 call_tool）
           ├── 桌面/屏幕   desktop_tools system_tools screen_tools ime_tools window_manager
           ├── 浏览器      browser_tools browser_connect browser_explorer browser_self_healing
           ├── 知识/学习   learning sessions memory_rag episodic_memory suggestions skills_runtime
           ├── 渠道        channels*.py + wecom_crypto（签名/解密）
           └── 外部 agent  delegation agent_tools
                │
基础设施   _atomic（原子写+锁）  schema（版本迁移）  backup（备份/恢复）  audit（审计）
           log（分级日志）  config（配置/密钥）  workspace（人设/记忆装配）  _sandbox + risk_guardrails（安全）
```

## 进程模型

| 进程 | 启动方式 | 职责 | 会写哪些状态 |
|---|---|---|---|
| TUI | `uiu`（默认） | 交互式对话、面板、复制/导出 | sessions、MEMORY.md、config.yaml、logs、audit |
| 网关 | `uiu serve` | 渠道长轮询 + webhook HTTP 服务（线程池跑 agent） | 同上 + 每渠道会话 `gw-*` |
| 守护 | `uiu daemon start` | 后台 60s tick 跑定时任务、每日自动备份 | cron/jobs.json、backups、logs |
| 一次性 | 其余子命令 | init/show/config/doctor/backup/… | 依命令而定 |

三者共享同一个 workspace，因此**所有状态文件都必须走 `uiu._atomic`**（原子写 + 跨进程锁），
见下方「写入约定」。

## 一次对话的数据流

1. 输入来自 TUI `Composer` 或网关 `on_message`；
2. `agent.run_turn()` 组装 system prompt（`workspace.py` 拼 SOUL/IDENTITY/USER/MEMORY）+ 历史（`sessions.compact_messages` 控预算）；
3. 模型返回 tool_calls → `tools.call_tool()`：
   - `risk_guardrails` 先判定（`classify_path` 路径三态 / `classify_command` shell 语义）；
   - 需要确认时走 `confirm.py` 注册的宿主回调（TUI 弹框 / 网关无通道则放行并留痕）；
   - 执行结果写 **审计日志**（`audit.record`，"tool_call" + ok/denied/error + 耗时）；
4. 回合结束：会话落盘（`sessions.save_session`）、上下文用量刷新、TUI 渲染。

## 状态与写入约定

| 路径 | 内容 | 版本 | 写入方式 |
|---|---|---|---|
| `config.yaml` | 模型/渠道/TUI 偏好 | `schema: 1` | `_atomic` + `schema.stamp`，读时自动迁移 |
| `.env` | 密钥（明文，仅当前用户可读） | — | `_atomic.atomic_write_text` |
| `sessions/*.json` | 会话 | `schema: 1` | `_atomic` + `file_lock`，损坏自动备份为 `.corrupt-<ts>` |
| `cron/jobs.json` | 定时任务 | `schema: 1`（v0 是裸 list） | `locked_update_json`（**迁移在锁内**） |
| `MEMORY.md` / `skills/` | 记忆与技能 | — | `_atomic` |
| `logs/uiu.log` | 分级日志（5MB×3 轮转） | — | `log.setup_logging` |
| `audit/uiu-audit.jsonl` | 工具执行与确认审计（脱敏、5MB 滚动） | — | 追加 + 锁 + fsync |
| `backups/*.zip` | 备份（滚动 7 份） | — | `backup.create_backup` |

## 安全模型

三层，逐层收紧：

1. **路径**：`workspace` / cwd / 临时目录放行；其他路径**需用户确认**；凭据目录（`.ssh`、`.aws`、
   Chrome User Data、Windows Credentials、`.uiu`…）与系统目录**直接拒绝**。
2. **命令**：只读动词放行；写/网络/进程/系统/包管理/解释器/未知命令**需确认**；破坏性命令（format、
   diskpart、shutdown…）**直接拒绝**。
3. **留痕**：每次工具执行与每次确认（approved/rejected/no_handler）都会写审计日志；密钥字段脱敏。

网关另有独立默认值：只绑 `127.0.0.1`；对外监听必须显式提供 `UIU_GATEWAY_TOKEN`。
详见 [gateway-api.md](gateway-api.md)。

## 关键约定（改代码前先读）

- 状态文件一律 `uiu._atomic`；`file_lock` 是「进程内 RLock + 跨进程 OS 锁」两层，缺一不可。
- 覆写 Textual 的 watcher/生命周期方法时，基类有同名实现就必须调 `super()`。
- 生成物（`docs/tools.md`、`docs/preview/*.svg`）不要手改，用脚本重新生成。
- 完整约定与踩坑清单见仓库根目录 `AGENTS.md`。
