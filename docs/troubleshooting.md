# 故障排查

按「症状 → 原因 → 处置」组织。多数问题先跑 `uiu doctor --lint` 看结论。

## 启动即失败

### `config.yaml 解析失败`

配置被写坏了（手改 YAML 缩进、编辑器截断）。`uiu doctor` 能识别：

```bash
uiu doctor --lint        # 看到 config/parse-error
uiu doctor --fix --yes   # 把坏文件备份成 config.yaml.bak 后重置为默认
```

### 网关拒绝启动：`拒绝在 0.0.0.0 上无鉴权启动网关`

这是安全默认。三选一：

```bash
uiu config --set-secret UIU_GATEWAY_TOKEN=<随机串>   # 推荐
uiu serve --host 127.0.0.1                          # 只本机
UIU_GATEWAY_INSECURE=1 uiu serve --host 0.0.0.0     # 明知风险（会告警）
```

## 模型/密钥

### 对话中途报 401 / `invalid_api_key`

`.env` 里没有对应 key，或 key 与 `model.api_key_env` 不匹配：

```bash
uiu show                  # 看 api_key_env 与 “-> set / NOT SET”
uiu config --api-key sk-xxx
uiu model                 # 交互式换 provider/模型
```

## 工具与权限

### 工具返回 `[blocked] 安全卫士拦截`

命中破坏性命令或凭据/系统路径。这是**设计如此**：关机、格式化、写系统目录、读 `.ssh`/`.env`
一类操作需要你手工执行。确认无误就自己跑，不要试图绕过。

### 工具要求确认

写文件、workspace 之外读写、网络/进程/系统类命令都会弹确认框，且框里会显示**完整命令与 cwd**。
网关等无交互场景没有确认通道，会放行并在审计里记为 `no_handler`。

### 想事后追责/排查

```bash
uiu audit --tail 50        # 谁在什么时候执行了什么、确认与否
uiu audit --json           # 原始 JSONL
```

## 数据

### 会话/任务文件损坏，或看到 `.corrupt-<时间戳>` 文件

读取到损坏 JSON 时会自动**备份为 `.corrupt-<ts>` 再当空处理**，不会静默丢数据。原始内容就在旁边，
可手工修回来。

### 误删/误改想恢复

```bash
uiu backup --list          # 每天自动备份一份（daemon 起手做），也可手工 uiu backup
uiu restore <zip>          # 覆盖前会自动再存一份 pre-restore 快照
```

## 环境

### Windows 控制台中文乱码

控制台编码不是 UTF-8 时会出现。用 Windows Terminal，或

```powershell
chcp 65001; $env:PYTHONIOENCODING='utf-8'
```

### `PermissionError` 写某个目录

受限环境（沙箱、被 ACL 收紧的目录、只读盘）常见。检查 `UIU_WORKSPACE` 是否指向可写目录；
守护进程状态目录可用 `UIU_HOME` 重定向。

### 浏览器/UIA/语音功能报缺依赖

这些是可选栈，按需安装：

```bash
pip install "uiu[browser]"    # playwright + browser-use（还要 playwright install chromium）
pip install "uiu[desktop]"    # Windows UIA 控件定位
pip install "uiu[voice]"      # TTS + STT
pip install "uiu[mcp]"        # 外部工具协议
```

## 还是不行

- 日志：`<workspace>/logs/uiu.log`（5MB×3 轮转，`UIU_LOG_LEVEL=DEBUG` 更详细）
- 自检：`uiu doctor --lint`
- 冒烟：`python cli_smoke.py`
