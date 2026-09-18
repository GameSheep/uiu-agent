# 隐私与数据处理

> **一句话**：uiu 是跑在**你自己机器上**的软件。我们没有服务器、不收集你的数据。
> 你说了什么、屏幕上有什么，要么只在本机处理，要么直接发给你**自己配置的**模型/渠道服务商。

- 适用版本：`0.2.0b1` 及以后
- 适用对象：把 uiu 装在自己机器上的个人用户

---

## 1. 数据都存在哪

| 数据 | 位置 | 形态 | 谁能看到 |
|---|---|---|---|
| 对话记录 | `<workspace>/sessions/*.json` | **明文** | 本机账号；备份 zip 里也有 |
| 人设 / 记忆 | `SOUL.md` / `IDENTITY.md` / `USER.md` / `MEMORY.md` | 明文 | 同上 |
| 技能 | `<workspace>/skills/` | 明文 | 同上 |
| **API key / 渠道凭据** | `<workspace>/.env` | **明文** | 同上（见 §4 风险） |
| 日志 | `<workspace>/logs/uiu.log`（5MB×3 轮转） | 明文 | 同上 |
| 审计记录 | `<workspace>/audit/uiu-audit.jsonl` | 明文（敏感字段已脱敏） | 同上 |
| 备份 | `<workspace>/backups/*.zip` | 明文 zip | 同上 |
| 回收站 | `<workspace>/.trash/` | 明文 | 同上（默认留 7 天） |

默认 workspace 是 `~/.uiu/workspace`；可用 `--workspace` 或 `UIU_WORKSPACE` 换位置，
用 `UIU_HOME` 把「用户级目录」整体重定向（例如放到加密盘）。

## 2. 数据会发给谁（出站流向）

**只有你配置过的东西才会收到数据。**

| 场景 | 去向 | 触发条件 |
|---|---|---|
| 对话 / 工具结果 | 你配置的模型服务商（OpenAI·Anthropic·OpenRouter·NVIDIA·Google·自建兼容端点等） | 每次发消息；**这是模型工作的前提** |
| 收发的消息 | 你启用的渠道平台（微信 / 飞书 / 企微 / 钉钉 / Slack / Discord / 邮件） | 你配置并启用了该渠道 |
| 安装技能 | `raw.githubusercontent.com` / `github.com` / `api.github.com` | 你执行 `uiu skills install` |
| 检查更新 / 发布 | `pypi.org` / `test.pypi.org` | 你执行 `uiu update` / `uiu publish` |
| 联网搜索工具 | DuckDuckGo 等搜索端点 | 模型调用联网搜索工具 |
| 网关 | `127.0.0.1`（**默认只绑本机**） | 你启动 `uiu serve` 且未改 `--host` |

### 屏幕与桌面自动化

- 截图、图像比对、**OCR 全部在本机完成**（本地 rapidocr / Windows 原生 OCR），画面不会上传。
- **例外**：如果你配置的是「视觉模型」并让它看屏幕，那一张截图会作为消息发给你自己的模型服务商
  ——这是你选择该模型的结果，不是我们转发的。

## 3. 我们明确不做的事

- **没有遥测、没有埋点、没有崩溃上报**：代码里不存在任何分析 SDK 或上报端点
  （`tests/test_privacy.py` 守着这条断言）。
- **不代理你的模型调用**：请求从你的机器直连你配置的服务商。
- 不擅自上传 workspace 内容；`uiu backup` 只写本地 zip。
- 不做「悄悄安装」：装可选能力要显式 `pip install 'uiu[...]'` 或 `uiu doctor --fix --install-deps`。

## 4. 风险与限制（诚实说清楚）

1. **API key 是明文文件**（`.env`）。请把它当密码对待：不要把 workspace 传到网盘、
   不要把 `.env` 贴进聊天；备份 zip 含 `.env`（`uiu backup` 会提示这一点）。
2. **提示注入（prompt injection）**：agent 会读屏幕/文件/网页。若其中藏有恶意指令，
   模型可能被诱导去调用工具。我们做了缓解（高风险操作需确认、路径白名单、凭据目录拒绝、
   破坏性命令拦截、全程审计），但**不能保证 100% 拦住**。涉及转账/删除/发送的场景请保持人工确认。
3. **渠道平台必然能看到消息**：消息要经过对方服务器才能送达，这不受我们控制。
4. **删除不等于物理擦除**：会话/备份/回收站删除后，磁盘上仍可能残留（SSD 磨损均衡、
   文件系统日志）。需要强保证请用全盘加密。
5. **不要输入他人的敏感数据**：身份证号、他人病历、密码等不应贴进对话——它们会被发给模型服务商。

## 5. 你能怎么自查与清理

```bash
uiu audit                      # 看工具调用记录（含被拦截的）
uiu audit --json | jq .data.events    # 脚本化审计
uiu sessions usage             # 会话占用；uiu sessions prune 清理（先进回收站）
uiu trash                      # 删除是可撤销的；--purge 彻底清
uiu backup --list              # 备份清单（含 .env，注意保管）
uiu show                       # 当前模型/渠道/密钥状态（不打印密钥本身）
```

彻底清空：删掉整个 workspace 目录（默认 `~/.uiu/workspace`）与 `UIU_HOME` 下的运行时。

## 6. 附：本程序会联系的外部主机（白名单）

> 这份清单是**测试的唯一来源**：源码里出现未列出的主机，`tests/test_privacy.py` 会失败。
> 想加新端点，必须先在这里说清楚它是干嘛的。

```text
# --- 你配置的模型服务商（= uiu model 里的预设列表，只有你选了才会连）---
api.openai.com
api.anthropic.com
generativelanguage.googleapis.com
openrouter.ai
integrate.api.nvidia.com
inference-api.nousresearch.com
router.huggingface.co
ai-gateway.vercel.sh
opencode.ai
ollama.com
api.deepseek.com
api.moonshot.cn
api.z.ai
api.x.ai
api.xiaomimimo.com
dashscope.aliyuncs.com
coding.dashscope.aliyuncs.com
token-plan.cn-beijing.maas.aliyuncs.com
api.siliconflow.cn
api.stepfun.ai
api.fireworks.ai
api.novita.ai
api.tokenfactory.nebius.com
api.gmi-serving.com
api.kilo.ai
api.arcee.ai
api.deepinfra.com
api.upstage.ai
# --- 你启用的渠道平台 ---
api.dingtalk.com
open.feishu.cn
qyapi.weixin.qq.com
api.telegram.org
discord.com
slack.com
graph.facebook.com
smtp.*
# --- 技能安装 / 分发 ---
raw.githubusercontent.com
github.com
github
api.github.com
pypi.org
upload.pypi.org
test.pypi.org
# --- 联网检查 / 搜索工具 ---
lite.duckduckgo.com
www.baidu.com
# --- 本机地址与文档示例占位（占位域名不会被真的请求）---
localhost
127.0.0.1
api.example.com
api.xxx.com
xxx
```

> 说明：`0.0.0.0` 只作为**监听地址**出现在网关绑定逻辑里（表示「不限制来源」），
> 不是出站目标，因此不在本表；网关默认仍只绑 `127.0.0.1`。

## 7. 变更

本文件随版本更新；数据流向有实质变化时会在 CHANGELOG 里注明。
问题或异议请开 issue：<https://github.com/GameSheep/uiu-agent/issues>
