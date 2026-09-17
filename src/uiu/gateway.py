"""Gateway — runs all enabled channels, routes messages to the agent.

`uiu serve` 启动后：
- Telegram: 长轮询 getUpdates
- Feishu / WeCom: 起一个本地 HTTP server 接收 webhook（飞书/企微需要公网回调，
  或内网穿透把回调指到这里）
- 每条进来的消息按 chat_id 维护独立会话，调用 agent loop 回复

并发用 asyncio；agent 调用是同步的，用 asyncio.to_thread 跑。
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import channels
from .agent import run_turn
from .config import AppConfig, ChannelConfig, load_config, parse_env_file
from .llm import make_client
from .workspace import Workspace, load_workspace


# --------------------------------------------------------------------------
# 绑定与鉴权策略
# --------------------------------------------------------------------------
# 网关能把任意入站文本喂给本机工具（shell / 文件写 / 微信发送），
# 所以在没有鉴权的情况下暴露到非本机地址，等于把执行权交给能连上端口的人。
# 策略：默认只绑 127.0.0.1；要对外监听必须显式提供 UIU_GATEWAY_TOKEN，
# 或者显式承认风险（UIU_GATEWAY_INSECURE=1）。

_LOOPBACK = {"127.0.0.1", "localhost", "::1", "0:0:0:0:0:0:0:1"}


def _is_loopback(host: str) -> bool:
    h = (host or "").strip().lower().strip("[]")
    return h in _LOOPBACK or h.startswith("127.")


def resolve_bind(host: str = "", token: str = "") -> tuple[str, list[str]]:
    """Return (bind_host, warnings) or raise RuntimeError for an unsafe bind."""
    import os as _os

    chosen = (host or _os.environ.get("UIU_GATEWAY_HOST", "") or "127.0.0.1").strip() or "127.0.0.1"
    insecure = _os.environ.get("UIU_GATEWAY_INSECURE", "").strip().lower() in ("1", "true", "yes", "on")
    warnings: list[str] = []
    if _is_loopback(chosen):
        if not token:
            warnings.append("未设置 UIU_GATEWAY_TOKEN —— 已只监听本机（安全默认）")
        return chosen, warnings
    if token:
        return chosen, warnings
    if insecure:
        warnings.append(f"UIU_GATEWAY_INSECURE=1：{chosen} 对外监听且无鉴权，任何能连上端口的人都能驱动本机工具")
        return chosen, warnings
    raise RuntimeError(
        f"拒绝在 {chosen} 上无鉴权启动网关。任选其一：\n"
        f"  1) 设置网关 token（推荐）: uiu config --set-secret UIU_GATEWAY_TOKEN=<随机串>\n"
        f"  2) 只监听本机: --host 127.0.0.1 或 UIU_GATEWAY_HOST=127.0.0.1\n"
        f"  3) 明知风险仍要对外暴露: UIU_GATEWAY_INSECURE=1"
    )


def auth_status(token: str) -> str:
    return "已启用（X-Gateway-Token）" if token else "未启用"


class Gateway:
    MAX_SESSIONS = 500
    MAX_MESSAGE_CHARS = 20000

    def __init__(self, cfg: AppConfig, ws: Workspace):
        self.cfg = cfg
        self.ws = ws
        self.client = make_client(cfg.model)
        self.tool_schemas = _build_tool_schemas(ws)
        self.sessions: dict[str, list[dict]] = {}  # chat_id -> messages
        self.adapters: list = []
        self._origin: dict[str, str] = {}  # chat_id -> channel name
        self._lock = threading.Lock()
        self._pending: dict[str, "queue.Queue[str]"] = {}  # clarify 等待下一条消息
        self._local = threading.local()
        # agent 调用线程池：run_turn 是同步的，不能阻塞共享 event loop
        self._executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="gw-agent")
        # 可选网关鉴权：设 UIU_GATEWAY_TOKEN 后 webhook 需带 X-Gateway-Token
        import os as _os
        self._gateway_token = _os.environ.get("UIU_GATEWAY_TOKEN", "")
        self._bind_host = "127.0.0.1"
        try:
            from .delegation import set_context as _set_delegation_ctx
            _set_delegation_ctx(self.client, cfg.model, ws, self.tool_schemas)
        except Exception:
            pass
        try:
            from .clarify import set_ask_handler as _set_ask
            _set_ask(self._ask_via_chat)
        except Exception:
            pass
        # 记忆热刷新：memory_add 写入后，本 gateway 的 ws.memory 立即更新
        try:
            from .learning import register_memory_hook as _reg_mem_hook
            _reg_mem_hook(ws.reload_memory)
        except Exception:
            pass

    def _ask_via_chat(self, question: str, options: list[str] | None) -> str:
        """clarify 网关实现：发问题到当前聊天，阻塞等下一条消息（120s 超时）。"""
        import queue as _queue
        chat_id = getattr(self._local, "chat_id", "")
        if not chat_id:
            return ""
        text = question
        if options:
            text += "\n" + "\n".join(f"{i}. {o}" for i, o in enumerate(options, 1))
        q: _queue.Queue[str] = _queue.Queue()
        with self._lock:
            self._pending[chat_id] = q
        try:
            self._send_to_chat(chat_id, text)
            return q.get(timeout=120)
        except Exception:
            return ""
        finally:
            with self._lock:
                self._pending.pop(chat_id, None)

    def _send_to_chat(self, chat_id: str, text: str) -> None:
        with self._lock:
            origin_name = dict(self._origin).get(chat_id, "")
            adapters = list(self.adapters)
        for ad in adapters:
            if ad.config.name == origin_name:
                ad.send(chat_id, text)
                return
        for ad in adapters:
            ok, _ = ad.send(chat_id, text)
            if ok:
                return

    def _session_messages(self, chat_id: str) -> list[dict]:
        with self._lock:
            if chat_id not in self.sessions:
                if len(self.sessions) >= self.MAX_SESSIONS:
                    # 驱逐最旧会话，防内存刷爆
                    oldest = next(iter(self.sessions))
                    del self.sessions[oldest]
                self.sessions[chat_id] = [{"role": "system", "content": self.ws.system_prompt()}]
            return self.sessions[chat_id]

    def on_message(self, chat_id: str, text: str) -> None:
        """Called by an adapter when a message arrives. Runs agent + sends reply."""
        chat_id = str(chat_id or "")[:128]
        text = (text or "")[: self.MAX_MESSAGE_CHARS]
        if not chat_id or not text.strip():
            return
        # clarify 等待中：这条消息是答案，直接投递，不跑 agent
        with self._lock:
            pending = self._pending.get(chat_id)
        if pending is not None:
            try:
                pending.put_nowait(text)
            except Exception:
                pass
            return
        # slash 命令（TUI 同款注册表）
        if text.startswith("/") and not text.startswith("//"):
            from .slash import SlashContext, dispatch
            say_out: list[str] = []

            def _say(t: str) -> None:
                say_out.append(t)

            sctx = SlashContext(ws=self.ws, cfg=self.cfg, client=self.client,
                                 messages=None, chat_id=chat_id, say=_say,
                                 tool_schemas=self.tool_schemas)
            try:
                dispatch(text, sctx)
            except Exception as e:
                say_out.append(f"[error] {type(e).__name__}: {e}")
            if say_out:
                self._send_to_chat(chat_id, "\n".join(say_out))
            return
        self._local.chat_id = chat_id
        print(f"[gateway] {chat_id}: {text[:60]}", flush=True)
        messages = self._session_messages(chat_id)
        messages.append({"role": "user", "content": text})
        try:
            reply = run_turn(
                client=self.client,
                messages=messages,
                tool_schemas=self.tool_schemas,
                skills=self.ws.skills,
                model=self.cfg.model.default,
                cfg=self.cfg.model,
            )
            print(f"[gateway] reply: {reply[:60]}", flush=True)
        except Exception as e:
            reply = f"[error] {type(e).__name__}: {e}"
        # send back on the originating adapter
        with self._lock:
            origin_name = dict(self._origin).get(chat_id, "")
        for ad in self.adapters:
            if ad.config.name == origin_name:
                ok, msg = ad.send(chat_id, reply)
                if not ok:
                    print(f"[gateway] send failed ({ad.name}): {msg}", file=sys.stderr)
                self._persist(chat_id, messages)
                return
        # fallback: send on any adapter
        for ad in self.adapters:
            ok, msg = ad.send(chat_id, reply)
            if ok:
                self._persist(chat_id, messages)
                return
        self._persist(chat_id, messages)

    def _persist(self, chat_id: str, messages: list[dict]) -> None:
        """会话落盘（compact 后存，重启可 resume）。"""
        try:
            from .sessions import compact_messages, save_session
            save_session(self.ws.root, f"gw-{chat_id}", compact_messages(messages))
        except Exception as e:
            print(f"[gateway] persist failed: {e}", file=sys.stderr)

    def _origin_channel(self) -> dict[str, str]:
        return self._origin

    def run(self, port: int = 8765, host: str = "") -> None:
        """Start all enabled channel adapters + webhook server, block forever."""
        enabled = [c for c in self.cfg.channels if c.enabled]
        if not enabled:
            print("没有 enabled 的 channel。先: uiu channel add <name> --type <telegram|feishu|wecom>")
            return

        # 启动时连接配置的 MCP 服务器（best-effort，失败不影响 serve）
        try:
            from .mcp_tools import try_connect_all as _mcp_connect
            for line in _mcp_connect(self.cfg):
                print(line, flush=True)
        except Exception as e:
            print(f"[gateway] MCP 初始化失败（忽略）: {type(e).__name__}: {e}", file=sys.stderr)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        http_server = None
        feishu_wecom = [c for c in enabled if c.type in ("feishu", "wecom", "webhook")]
        if feishu_wecom:
            http_server = self._start_http_server(port, host)

        for c in enabled:
            adapter = channels.create_adapter(c, on_message=None)
            if adapter is None:
                print(f"[gateway] 无法创建 adapter: {c.name} ({c.type})")
                continue
            # wire on_message: record origin chat->channel, then run agent
            orig_on_message = self.on_message

            def make_handler(ad):
                def handler(chat_id, text):
                    with self._lock:
                        self._origin[chat_id] = ad.config.name
                    # run agent off the event-loop thread: run_turn is synchronous
                    # and would otherwise block every other adapter sharing the loop
                    try:
                        self._executor.submit(orig_on_message, chat_id, text)
                    except RuntimeError:
                        orig_on_message(chat_id, text)
                return handler
            adapter.on_message = make_handler(adapter)
            self.adapters.append(adapter)

            print(f"[gateway] 启动 {c.name} [{c.type}]")
            try:
                ok, msg = adapter.check()
                if not ok:
                    print(f"[gateway]  !! {c.name} 凭据无效: {msg}")
            except Exception as e:
                print(f"[gateway]  !! {c.name} check 异常: {e}")
            adapter.start()

        # cron tick 线程：每 60s 跑到期任务
        cron_stop = threading.Event()

        def _cron_loop():
            from . import cron as _cron
            while not cron_stop.wait(60):
                try:
                    ran = _cron.tick(self.ws.root)
                    for out in ran:
                        print(f"[cron] ran → {out}", flush=True)
                except Exception as e:
                    print(f"[cron] tick failed: {e}", file=sys.stderr)

        threading.Thread(target=_cron_loop, daemon=True).start()

        try:
            if http_server:
                shown = self._bind_host if self._bind_host not in ("0.0.0.0", "") else "127.0.0.1"
                print(f"[gateway] webhook 服务器: http://{shown}:{port}  (飞书/企微回调指到这里)")
            loop.run_forever()
        except KeyboardInterrupt:
            print("\n[gateway] 停止…")
        finally:
            cron_stop.set()
            for ad in self.adapters:
                ad.stop()
            if http_server:
                http_server.shutdown()
            loop.close()
            self._executor.shutdown(wait=False, cancel_futures=True)

    def _start_http_server(self, port: int, host: str = "") -> ThreadingHTTPServer:
        gate = self
        bind_host, warnings = resolve_bind(host, self._gateway_token)
        self._bind_host = bind_host
        for warning in warnings:
            print(f"[gateway] 警告: {warning}", file=sys.stderr, flush=True)
        print(f"[gateway] 鉴权 {auth_status(self._gateway_token)} · 监听 {bind_host}:{port}", flush=True)

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                pass  # silence

            def do_GET(self):
                # WeCom URL verification: echostr
                if self.path.startswith("/wecom"):
                    qs = dict(x.split("=", 1) for x in self.path.split("?", 1)[-1].split("&") if "=" in x)
                    for ad in gate.adapters:
                        if ad.name == "wecom":
                            resp = ad.verify_url(qs)
                            self._json(resp)
                            return
                    echo = qs.get("echostr", "")
                    self._json({"errcode": 0, "errmsg": "ok", "echostr": echo})
                    return
                if self.path.startswith("/api/channels"):
                    if gate._gateway_token and self.headers.get("X-Gateway-Token", "") != gate._gateway_token:
                        self._json({"code": 1, "msg": "unauthorized"}, status=401)
                        return
                    self._json({"channels": [
                        {"name": ad.config.name, "type": ad.name,
                         "enabled": ad.config.enabled} for ad in gate.adapters]})
                    return
                if self.path.startswith("/whatsapp"):
                    # Meta 回调校验：hub.mode=subscribe & hub.verify_token 对上即回 challenge
                    qs = dict(x.split("=", 1) for x in self.path.split("?", 1)[-1].split("&") if "=" in x)
                    for ad in gate.adapters:
                        if ad.name == "whatsapp" and qs.get("hub.mode") == "subscribe" \
                                and qs.get("hub.verify_token") == ad.verify:
                            self._json(int(qs.get("hub.challenge", "0")) or {"ok": True})
                            return
                    self._json({"code": 1, "msg": "verify failed"}, status=403)
                    return
                self._json({"ok": True, "service": "uiu gateway"})

            def do_POST(self):
                MAX_BODY = 1 * 1024 * 1024  # 1MB 上限，防内存 DoS
                # 网关 token 只卡 /api/* 与 /generic/*；各平台回调走自有校验
                #（飞书 verify_token、企微/WhatsApp 签名），避免公网回调被误杀
                if self.path.startswith(("/api/", "/generic")) and gate._gateway_token:
                    got = self.headers.get("X-Gateway-Token", "")
                    if got != gate._gateway_token:
                        self._json({"code": 1, "msg": "unauthorized"}, status=401)
                        return
                try:
                    length = int(self.headers.get("Content-Length", 0))
                except (TypeError, ValueError):
                    self._json({"code": 1, "msg": "bad length"}, status=400)
                    return
                if length <= 0 or length > MAX_BODY:
                    self._json({"code": 1, "msg": "bad length"}, status=400)
                    return
                try:
                    raw = self.rfile.read(length)
                    body = json.loads(raw.decode("utf-8"))
                except Exception:
                    self._json({"code": 1, "msg": "bad json"}, status=400)
                    return
                if self.path.startswith("/feishu"):
                    for ad in gate.adapters:
                        if ad.name == "feishu":
                            resp = ad.handle_webhook(body)
                            self._json(resp)
                            return
                if self.path.startswith("/wecom"):
                    qs = dict(x.split("=", 1) for x in self.path.split("?", 1)[-1].split("&") if "=" in x)
                    for ad in gate.adapters:
                        if ad.name == "wecom":
                            resp = ad.handle_webhook(body, qs)
                            self._json(resp)
                            return
                if self.path.startswith("/api/send"):
                    # api_server：编程方式外发消息 {chat_id, text, channel?}
                    if not isinstance(body, dict):
                        self._json({"code": 1, "msg": "bad body"}, status=400)
                        return
                    chat_id = str(body.get("chat_id", ""))[:128]
                    text = str(body.get("text", ""))[:20000]
                    want = str(body.get("channel", ""))
                    if not chat_id or not text.strip():
                        self._json({"code": 1, "msg": "chat_id/text 必填"}, status=400)
                        return
                    sent, info = False, "no adapter"
                    for ad in gate.adapters:
                        if want and ad.config.name != want and ad.name != want:
                            continue
                        ok, msg = ad.send(chat_id, text)
                        if ok:
                            sent, info = True, "sent"
                            break
                        info = msg
                    self._json({"code": 0 if sent else 1, "msg": info})
                    return
                if self.path.startswith("/generic"):
                    # 通用 webhook 平台：/generic/<name>，body 按 adapter options 取字段
                    rest = self.path[len("/generic"):].strip("/")
                    qs = dict(x.split("=", 1) for x in self.path.split("?", 1)[-1].split("&") if "=" in x)
                    for ad in gate.adapters:
                        if ad.name == "webhook" and ad.config.name == rest:
                            resp = ad.handle_webhook(body, qs.get("secret", ""))
                            self._json(resp)
                            return
                if self.path.startswith("/whatsapp"):
                    for ad in gate.adapters:
                        if ad.name == "whatsapp":
                            resp = ad.handle_webhook(body)
                            self._json(resp)
                            return
                self._json({"code": 1, "msg": "no adapter"})

            def _json(self, obj, status: int = 200):
                data = json.dumps(obj).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        server = ThreadingHTTPServer((bind_host, port), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server


def _build_tool_schemas(ws: Workspace) -> list[dict]:
    from . import tools
    schemas = tools.tool_defs()
    for skill in ws.skills:
        schemas.append(skill.to_tool_def())
    return schemas