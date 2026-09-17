# 网关 HTTP API

`uiu serve` 会为飞书/企微/WhatsApp/通用 webhook 起一个 HTTP 服务（默认端口 8765）。
本文档对应 `src/uiu/gateway.py` 的实现。

## 启动与绑定

```bash
uiu serve                      # 默认只监听 127.0.0.1:8765（安全默认）
uiu serve --port 9000
uiu serve --host 0.0.0.0       # 对外监听：必须先设 UIU_GATEWAY_TOKEN，否则拒绝启动
```

| 环境变量 | 作用 |
|---|---|
| `UIU_GATEWAY_TOKEN` | 设置后 `/api/*` 与 `/generic/*` 必须带 `X-Gateway-Token` |
| `UIU_GATEWAY_HOST` | 等价于 `--host` |
| `UIU_GATEWAY_INSECURE` | 显式承认风险：允许「对外监听 + 无鉴权」启动（会打警告） |

启动时会打印真实状态：`[gateway] 鉴权 已启用（X-Gateway-Token） · 监听 127.0.0.1:8765`。
为什么这样设计：网关能把任意入站文本喂给本机工具（shell / 文件写 / 发消息），
无鉴权对外监听等于把执行权交出去。

## 鉴权矩阵

| 端点 | 鉴权方式 |
|---|---|
| `GET /api/channels` | `X-Gateway-Token`（设置了 token 时） |
| `POST /api/send` | `X-Gateway-Token`（设置了 token 时） |
| `POST /generic/<name>` | 网关 token **且** 渠道 `secret`（渠道未配 secret 直接拒绝投递） |
| `POST /feishu` | 飞书 `verify_token`（渠道自有校验） |
| `GET/POST /wecom` | 企微 `msg_signature` 校验 + AES 解密 |
| `GET/POST /whatsapp` | Meta `hub.verify_token` 校验 |
| `GET /` | 无鉴权的健康响应（`{"ok": true, "service": "uiu gateway"}`） |

平台回调走各自签名，是为了避免公网回调被网关 token 误杀；所以**对外暴露时务必同时配好
平台侧校验参数**。

## 端点

### `GET /`

健康检查。

```json
{"ok": true, "service": "uiu gateway"}
```

### `GET /api/channels`

列出已加载渠道（需 token）。

```bash
curl -H "X-Gateway-Token: ***" http://127.0.0.1:8765/api/channels
```

```json
{"channels": [{"name": "ext", "type": "webhook", "enabled": true}]}
```

### `POST /api/send`

以编程方式外发消息（需 token）。

```bash
curl -X POST http://127.0.0.1:8765/api/send \
  -H "X-Gateway-Token: ***" -H "Content-Type: application/json" \
  -d '{"chat_id": "u1", "text": "hi", "channel": "ext"}'
```

`channel` 可省略（会尝试所有适配器）。返回 `{"code": 0, "msg": "sent"}` 或 `{"code": 1, "msg": "..."}`。

### `POST /generic/<渠道名>`

任意系统把 JSON POST 进来即变消息源（需 token + 渠道 secret）。

```bash
uiu channel add ext --type webhook -o secret=<随机串> -o chat_field=user.id -o text_field=message
curl -X POST http://127.0.0.1:8765/generic/ext \
  -H "X-Gateway-Token: ***" -H "Content-Type: application/json" \
  -d '{"user": {"id": "u1"}, "message": "你好", "secret": "<随机串>"}'
```

- `chat_field` / `text_field`：点分路径，默认 `chat_id` / `text`；
- `secret`：也可用 `?secret=` 传入；**未配置 secret 的渠道一律拒绝投递**（返回 `code: 1`）。

### `POST /feishu`、`GET|POST /wecom`、`GET|POST /whatsapp`

平台回调入口，按各平台协议解析（飞书 `im.message.receive_v1`、企微 AES 加密包、WhatsApp
`entry[].changes[].value.messages`）。回调地址分别填 `/feishu`、`/wecom`、`/whatsapp`。

## 返回约定

| 情况 | HTTP | 响应体 |
|---|---|---|
| 渠道适配器处理 | 200 | `{"code": 0}` 成功；`{"code": 1, "msg": "..."}` 拒绝（如 secret 不对） |
| 缺/错 token | 401 | `{"code": 1, "msg": "unauthorized"}` |
| 平台校验失败 | 403 | `{"code": 1, "msg": "..."}`（如 `verify failed`） |
| body 非法 / 过大（>1MB） | 400 | `{"code": 1, "msg": "bad json" / "bad length"}` |
| 路径未匹配 | 200 | `{"code": 1, "msg": "no adapter"}` |

## 运维

- 日志：`<workspace>/logs/uiu.log`（`UIU_LOG_LEVEL` 控级别）；
- 审计：`<workspace>/audit/uiu-audit.jsonl`（`uiu audit` 查看）——入站消息触发的每次工具执行都在里面；
- 会话：渠道会话以 `gw-*` 落在 `<workspace>/sessions/`；
- 定时任务：网关进程内每 60s 跑一次 `cron.tick`（真正的 OS 级锁防重入）。
