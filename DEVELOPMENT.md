# uiu 开发文档（完成度评审 + 对标差距 + 路线图）

> 评审日期：2026-09-04 · 版本基线：v0.1.5 · 方法：源码逐模块精读 + 真实启动验证 + 对照 Hermes / OpenClaw
>
> 一句话结论：**功能覆盖面已接近个人 IP agent 的完整形态，但存在一条把"已写好的能力"挡在运行时的工具注册表断链；在把 README 的承诺变成可运行现实之前，不宜宣称完成。**

> ## ✅ 2026-09-04 修复状态（本文件第 2-6 节的 P0/P1 已全部落地）
>
> 当日已完成并全量验证（132 个 pytest + 29 项 CLI smoke + 真实启动全绿）：
> - **P0 断链**：裸导入改相对导入、补 `WECHAT_TOOLS` 注册表（send_wechat 重新进表）、修 askui `_screenshot`/`_ocr_image` 引用 → `import uiu.tools` 通过（63 工具 / 17 组）。
> - **测试失真**：新增 `tests/test_tools_registry.py` 强制 import 注册表；`cli_smoke.py` 已补回并移出 .gitignore，CI smoke 步骤真实可跑。
> - **pyproject 虚假版本约束**：`rapidocr-onnxruntime>=1.3.0`（不存在）→ `>=1.2.3`；新增 `cryptography` 依赖。
> - **MCP 接线**：`mcp_tools.try_connect_all` 在 TUI/gateway 启动时连接；`mcp_call_tool_sync` 事件循环修复（消除协程泄漏告警）。
> - **记忆统一**：learning 与 RAG 写同一 MEMORY.md 同格式；注册 `memory_remove`；`Workspace.reload_memory()` + `register_memory_hook` 实现运行期热刷新（TUI/gateway//memory 均接入）；`skill_create` 不再写空 `exec:`。
> - **P1 硬伤**：telegram slash 透传、wecom 官方 AES 回调（`wecom_crypto.py` + 9 项加密测试）、browser 单例 atexit 关闭、voice whisper 缓存 + 去死代码、gateway agent 调用线程池化（不再阻塞 event loop）、cron 完整 5 段语法（`*/n`/范围/列表/星期，含周字段映射修正）、CLI `--workspace` 子命令后置可用。
> - **README**：工具数统一 62、补 memory_remove、企微 AES 配置说明、cron 语法更新。
> - **TUI**：slash 命令 tab 补全、删死代码 `SLASH_HELP`、`/memory` 热刷新。

---

## 1. 完成度总览

| 层 | 完成度 | 一句话 |
|---|---|---|
| CLI 子命令（13 个） | **90 / 100** | 全真实实现、有副作用与错误分类，`uiu model` 交互向导完整，是全局最成熟的面 |
| 核心对话循环 | **88 / 100** | 流式 + 多轮 tool-use + 双协议 + 上下文修复/压缩/重试，engine 本身健壮 |
| 工具实现本体（60+ 个） | **82 / 100** | 几乎无占位/假工具，多数带可选依赖优雅降级 |
| 工具注册表 & 桌面桥接层 | **20 / 100** | **import 即崩**，`WECHAT_TOOLS` 断链 + 裸导入，把上面所有实现挡在运行时之外 |
| TUI | **55 / 100** | 是"带历史/状态栏的流式 REPL"，不是真正的 TUI 应用；缺多行输入、流式 markdown、主题、快捷键 |
| Gateway / serve | **60 / 100** | 会话/cron/api/webhook/slash 全实现，但依赖断裂的注册表起不来；telegram 吞 slash、wecom 无官方解密 |
| 渠道 adapter（9 种） | **65 / 100** | email/telegram/feishu/dingtalk 较完整；discord/slack check 是假的；wecom 有安全缺口 |
| 测试 & CI | **58 / 100** | 13 个测试文件且绕过注册表所以全绿；**CI 引用的 cli_smoke.py 不在仓库里，smoke 步骤必然失败** |
| 自学习 / 记忆 | **62 / 100** | 落盘真，但 learning.py 与 RAG 是**两套互不相通**的记忆 API；运行期 ws.memory 不热刷新 |
| MCP | **25 / 100** | client 层完整，但 **connect_all 无人调用**，动态工具注册表永远是空的 |
| 文档 | **70 / 100** | README 详尽但**多处与代码不符**（工具数 63 vs 62、browser 降级、keyboard 校验、look 可用的说法均不实） |

**总评：约 6 成。** 这不是"骨架"——对话引擎、沙箱、CLI、OCR、桌面原子操作、cron 都是真材实料；但**一条 import 期断链 + 若干"写了但没接线"的模块**，决定了项目当前处于"零件齐全、未总装"的状态。

---

## 2. 必须知道的真实断点（P0，全部经运行验证）

### 2.1 `uiu.tools` import 即崩 —— 全系统启动不了

真实运行 `import uiu.tools`（TUI / serve / agent 的必经入口）结果：

```
File "src/uiu/desktop_tools.py", line 8, in <module>
    from gui_primitives import (   # ← 裸导入，应为 from .gui_primitives import
ModuleNotFoundError: No module named 'gui_primitives'
```

修好裸导入后，下一个必然崩溃点是 `tools.py:194`：

```
from .wechat_tools import WECHAT_TOOLS, wechat_tool_defs, call_wechat_tool
```

但 `wechat_tools.py` 里**这三个名字一个都不存在**（实际只导出 `SEND_WECHAT_DEF` / `send_wechat` / `execute_8step_send`），且 `tools.py:249` / `:289` 又在用 `**WECHAT_TOOLS` 展开。这是注册表层的 import 期 `NameError`。

连带影响：

- 8 步微信闭环 `send_wechat`（wechat_tools.py:128-228，写得很认真）因 `tools.py:219` 注释"经 WECHAT_TOOLS 注册"而**从注册表里彻底消失**，变成孤儿代码。
- `askui_tools.py:31` 引用 `screen_tools` 里**不存在的** `_screenshot` / `_ocr_image`（实际叫 `_ocr_full_screen`），`look()` 一调用即 `AttributeError`——README 却宣称它可用。
- 测试之所以全绿，是因为 `tests/conftest.py:10` 只把 `src/` 塞进 `sys.path`，各测试**直接 import 模块、从不 import `uiu.tools`**，于是绕过了整条断链。

> 判断：这是"完成了 80% 的工具、唯独忘了把它们装进注册表"的典型。修复本身是机械的（补 `WECHAT_TOOLS`/改用 `SEND_WECHAT_DEF`、改相对导入、修 `_screenshot` 引用），但**修完之前一切依赖工具表的入口都不可用**。

### 2.2 CI 的 smoke 步骤必然失败

`.github/workflows/ci.yml:26-27` 执行 `python cli_smoke.py`，但：

- `cli_smoke.py` 在 `.gitignore:22` 中被排除，**从未被 git 跟踪，仓库里不存在**；
- README「验证」一节同样引用它。

即：**当前 CI 在干净 checkout 上跑不到 smoke 这步就已在 import 阶段失败；即便修好注册表，smoke 脚本也缺失。**

### 2.3 MCP 动态工具是"写好了但没接线"

- `mcp_client.py:129` 有完整的 `connect_all()`；
- 但全仓**没有任何调用方**；
- `tools.py:268-273` 每轮调用 `mcp_tool_defs_list()`，因服务器从没连过，返回永远为空；
- 于是 README 声称的"MCP 动态注入工具"实际上**永不出现**，`mcp_servers` 配置项形同虚设。

### 2.4 记忆系统双轨分裂

同一份 `MEMORY.md`，存在**三套互相独立的写入路径、两套记忆工具**：

| 入口 | 文件/落点 | 运行期生效？ |
|---|---|---|
| `learning.py` 的 `memory_add`（注册为工具） | workspace 根 `MEMORY.md` | 落盘，但运行中 `ws.memory` **不热刷新**，要重启/重载 |
| `memory_rag.py` 的 `add_memory`（注册为工具） | 先写 MEMORY.md **再写向量库**（`~/.uiu/memory_vectors`） | 同上，向量库另存他处 |
| `/memory` slash 命令 | 直接 append `ctx.ws.root/MEMORY.md` | 即时但不与上面两套同步 |

同名不同义（`memory_add` vs `add_memory`）、落点不同、且都不更新运行期会话上下文——"自我学习闭环"实际是断的。

### 2.5 企业微信 adapter 未实现官方回调协议（安全缺口）

`channels_wecom.py:65-78` 的注释自认：**只收网关已鉴权的明文转发，未实现企微官方回调的 AES 解密 + 签名验证**；且不校验 `to` / `agentid`，任何能 POST 到 `/wecom` 的来源都可伪装成消息喂给 agent。feishu 相对完整（有 verify_token），wecom 是明文缺口。

---

## 3. 半成品清单（P1，按模块）

### 3.1 代码有实现、但存在硬伤

| 位置 | 问题 | 建议 |
|---|---|---|
| `desktop_tools.py:8-26`、`wechat_tools.py:95,130` | 6 处**裸导入**，包安装/常规 cwd 下必挂 | 全部改 `.gui_primitives` 相对导入 |
| `tools.py:335-345` | 通用异常处理块位于 `return` 之后，对 builtin 分支**永远不可达**；json 解析错误会裸抛 | 重构分发：先 try 再 return |
| `agent.py:19`、`llm.py:57-88` | 死代码：`_create` 从未调用、`_AnthropicResp` 适配器无人用 | 删除或并入 agent 的双协议路径 |
| `browser_tools.py:122-127` | 注释承诺"无 playwright 时降级 web_extract"，**实际只返回错误文本** | 兑现降级或删注释 |
| `browser_tools.py:86-96` | `_PAGE` 全局单例永不 close，每启一次泄漏一个 chromium | 进程退出时关闭 + 单例复用 |
| `gateway.py:102-167` | 注释说用 `asyncio.to_thread`，实际同步跑 `run_turn`（telegram 的 async `_listen` 会被阻塞） | 按注释改为 to_thread 或改文档 |
| `voice_tools.py:169` | 每次 `whisper.load_model("base")` 无缓存 | 进程级缓存模型实例 |
| `voice_tools.py:192` | `"zh-CN" if True else "en-US"` ——死代码式硬编码 | 按 voice_state 探测 |
| `skills_runtime.py` | `exec` 分发表只有 `echo`/`say_hello` 两个玩具，且 `say_hello` 没被任何 skill 引用；`skill_create` 写 `exec: ` 空行 → agent 建的 skill 无法当工具调 | 补文档说明、给 skill_create 模板填真实 exec 或删掉该机制 |
| `tools.py:289` 及周边 | DESKTOP 两套定义并存（原名 schema + `desktop_*` fn 包装），重构痕迹 | 收敛为单一路径 |
| `window_manager.py:110-121` | `launch_application` 兜底用 `shell=True` Popen，与 README"无 shell 解析防注入"矛盾 | 去 shell 或删 README 承诺 |
| `channels_telegram.py:59-60` | 收 `/` 开头消息直接 `continue` 丢弃 → 网关 slash 对 telegram 永不生效（与 README 冲突） | 把 `/` 消息交给 gateway 的 slash 分发 |
| `channels_dingtalk.py:99` | 群消息 send 只调 `groupMessages/send` 一种，"简化"注释 | 补单聊/多类型或文档说明 |
| `config.py:240-253` | `_load_config_fallback/_save_config_fallback` 名为 fallback、实际直接 `raise RuntimeError`（PyYAML 已是核心依赖，防御代码是死路） | 删掉或真实现 |
| `ime_tools.py` | 检测粒度只到 IME 开/关，检测不到微软拼音内的中/英子状态，可能多按一次 Shift 反而切错 | 文档注明边界；或走 UI 自动化增强 |
| `screen_tools.py:225-228` | docstring 称"区域 OCR 有 RapidOCR 备用"，实际区域只走 WinRT、无 RapidOCR 降级 | 兑现或改 docstring |
| `askui_tools.py:31,47-48` | `look()` 引用不存在的函数，必 AttributeError | 改引 `_ocr_full_screen` 对应真函数 |
| `safe_update.py:208` | Windows venv 路径硬编码 `Scripts/python.exe` | 探测或文档化 |
| `skill_installer.py` | GitHub API 未鉴权，60/h 限流会随机失败 | 可选项 + 重试 |

### 3.2 README 与代码不符（文档债）

| README 声称 | 实际 |
|---|---|
| "63 个内置工具"（行 8）/"62 个，17 组"（行 82） | 两处数字自相矛盾，且含 2.1 断链后实际跑不起来 |
| `send_wechat` 在工具表中 | 从注册表消失（孤儿代码） |
| `keyboard_shortcut` 校验合法键名 | `desktop_tools.py` schema 无任何键名校验 |
| browser 无 playwright 时降级 web_extract | 只返回错误文本 |
| `look` 可用 | import 即 AttributeError |
| MCP 动态注入工具 | connect_all 无人调用，永不注入 |
| 网关内 slash 与 TUI 同款 | telegram 收不到 `/` 消息 |
| `app_launch` 防注入无 shell | window_manager 兜底仍走 shell=True |
| "验证：cli_smoke.py" | 文件不存在 |

---

## 4. 对标 Hermes / OpenClaw：功能与 UI 差距

### 4.1 功能面（Hermes 对齐度较高，差距在"闭环"不在"清单"）

| 能力 | Hermes | OpenClaw | uiu 现状 | 差距 |
|---|---|---|---|---|
| 人设/SOUL + 记忆文件 | ✅ | ✅ | ✅ 完整 | 小 |
| Skills 渐进披露 | ✅ | ✅ | ✅ 索引+按需取全文+skill_* 工具化 | 小 |
| 自我学习循环（记记忆/沉淀技能） | ✅ | ✅ | ⚠️ 落盘真但运行期不生效、双轨分裂、nudge 只是文本 | **中** |
| 工具生态广度 | 中 | 广 | 广（60+）但注册表断链 | **大（先修 P0）** |
| 多 provider / 多协议 | ✅ | ✅ | ✅ openai 兼容 + anthropic 原生双活 | 小 |
| Cron 定时任务 | 部分 | ✅ | ✅ 间隔/daily/简化 cron/once + 锁 + tick | 中（cron 语法缩水） |
| 网关多渠道 | ✅ | ✅ | ⚠️ 9 adapter 但 telegram slash 失效、wecom 安全缺口 | 中 |
| MCP | ✅ | ✅ | ❌ 未接线 | **大** |
| 子 agent 派发 | ✅ | ✅ | ✅ 内建 + 外部 CLI 双轨 | 小 |
| 浏览器/桌面/OCR | — | ✅ | ⚠️ 真实现但裸导入 + 降级缺失 | 中 |
| RAG 向量记忆 | — | ✅ | ⚠️ 真实现但依赖可选、与 learning 分裂 | 中 |
| 会话持久化/压缩 | ✅ | ✅ | ✅ 自动存档/恢复/LLM 压缩 | 小 |

### 4.2 UI / 交互面（与 OpenClaw 差距最大，是"REPL"与"应用"的分水岭）

| 维度 | OpenClaw / Hermes 级 | uiu 现状 | 需要 |
|---|---|---|---|
| 布局 | 输入区/消息区/状态区分离的 full-screen 布局 | console.print 到同一滚动区，会与提示行交错 | prompt_toolkit full-screen 或 textual |
| 多行输入 | ✅ | 无（`session.prompt` 未开 multiline） | `multiline=True` + Meta+Enter 发送 |
| 流式 markdown | 代码块/表格直播高亮 | tty 下是**裸 token 流**，仅管道才有整段 Markdown | 分块渲染 markdown |
| 命令补全 | tab 补全 + 历史搜索 | 无 completer、无 Ctrl-R | prompt_toolkit Completer |
| 快捷键体系 | 新会话/清屏/中断/编辑器 | 仅 Ctrl-C/Ctrl-D | KeyBindings |
| 主题/配色 | 可配置 palette、dark/light | 颜色硬编码在 console.print 里 | 主题层 + 用户配置 |
| 状态机 | 明确 app 状态 + 错误恢复 | `_RunState` 三态 bool | 回合级状态机 + 错误回滚 |
| 顶栏/面板 | 顶部状态、可滚动消息 buffer | 仅一条 bottom_toolbar | 消息 buffer + 顶栏 |
| 进程内子界面 | 模型/技能选择面板 | 一律"退出到终端敲命令"（slash.py 自认） | TUI 内 dialog |

> 一句话：**CLI 是 90 分、TUI 是 55 分**。要追上 OpenClaw 的 TUI 体验，不是小改而是"把 REPL 重写成应用"的量级（可先走 prompt_toolkit full-screen 而非换 textual，保持单依赖）。

---

## 5. 路线图（按依赖排序）

### P0 —— 让它能跑起来（当前阻塞）
1. **修复工具注册表断链**（最高优先）：
   - `desktop_tools.py:8-26`、`wechat_tools.py:95,130` 改相对导入；
   - 补 `wechat_tools.py` 的 `WECHAT_TOOLS` 注册表（含 `SEND_WECHAT_DEF`/`send_wechat`），或把 `tools.py:194,249,289` 改引实际导出；
   - 修 `askui_tools.py:31` 的 `_screenshot`/`_ocr_image` 引用。
2. **补 `cli_smoke.py`**（从 .gitignore 移除或新建），让 CI 的 smoke 步骤真实可跑，并加一条"必须 `import uiu.tools` 成功"的冒烟断言（防止再出现绕过注册表的绿测试）。
3. **接线 MCP**：在 gateway/TUI 启动流程调用 `connect_all(config.mcp_servers)`，失败优雅降级。
4. **统一记忆入口**：指定 learning.py 的 `memory_add` 为唯一工具，删除/合并 RAG 双写；写入后热刷新 `ws.memory` 并重建 system prompt。

### P1 —— 让承诺兑现
5. 处理第 3 节全部"代码硬伤"（gateway to_thread、voice 缓存、browser 单例与降级、wecom AES、telegram slash 透传、键盘名校验等）。
6. **修 README**：工具数统一、删除/实现不符承诺、标注 Windows-only 边界。
7. 补 gateway 侧 `/save` `/resume` `/new`（当前因 messages=None 被拒）。
8. 提升 cron：支持 `*/n`、星期字段、run_job 真超时。

### P2 —— 对标 OpenClaw 的体验
9. **TUI 重写**（第 4.2 表，按序：multiline → 状态区分离 → 消息 buffer → 补全 → 主题 → 快捷键）。
10. 端到端验收矩阵：每个渠道至少一次"check→收→发"真实冒烟；桌面/OCR 工具加截图验收。
11. 记忆/自学习的运行期生效 + nudge 真实触发。
12. 打包质量：Windows 安装态验证（非源码树）、发布前核对 wheel 内容。

---

## 6. 验证基线（每个 P0 完成后的验收）

```bash
# 1. 注册表必须能 import，且工具数可数
python -c "import sys; sys.path.insert(0,'src'); import uiu.tools; print(len(uiu.tools.BUILTIN_TOOLS))"

# 2. 全量单测（当前绿，但必须改为"不绕过注册表"）
python -m pytest tests/ -q

# 3. CLI 冒烟（CI 同款，需先补 cli_smoke.py）
python cli_smoke.py

# 4. 真启动一次（TUI 无头冒烟 / serve 起停）
python -m uiu.main version
```

> 验收红线：**任何新测试不得绕过 `uiu.tools` 注册表直接 import 底层模块**——这正是本次评审发现的测试失真根源。
