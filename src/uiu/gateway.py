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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import channels
from .agent import run_turn
from .config import AppConfig, ChannelConfig, load_config, parse_env_file
from .llm import make_client
from .workspace import Workspace, load_workspace


class Gateway:
    def __init__(self, cfg: AppConfig, ws: Workspace):
        self.cfg = cfg
        self.ws = ws
        self.client = make_client(cfg.model)
        self.tool_schemas = _build_tool_schemas(ws)
        self.sessions: dict[str, list[dict]] = {}  # chat_id -> messages
        self.adapters: list = []
        self._origin: dict[str, str] = {}  # chat_id -> channel name

    def _session_messages(self, chat_id: str) -> list[dict]:
        if chat_id not in self.sessions:
            self.sessions[chat_id] = [{"role": "system", "content": self.ws.system_prompt()}]
        return self.sessions[chat_id]

    def on_message(self, chat_id: str, text: str) -> None:
        """Called by an adapter when a message arrives. Runs agent + sends reply."""
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
        for ad in self.adapters:
            if ad.config.name == self._origin_channel.get(chat_id, ""):
                ok, msg = ad.send(chat_id, reply)
                if not ok:
                    print(f"[gateway] send failed ({ad.name}): {msg}", file=sys.stderr)
                return
        # fallback: send on any adapter
        for ad in self.adapters:
            ok, msg = ad.send(chat_id, reply)
            if ok:
                return

    def _origin_channel(self) -> dict[str, str]:
        return self._origin

    def run(self, port: int = 8765) -> None:
        """Start all enabled channel adapters + webhook server, block forever."""
        enabled = [c for c in self.cfg.channels if c.enabled]
        if not enabled:
            print("没有 enabled 的 channel。先: uiu channel add <name> --type <telegram|feishu|wecom>")
            return

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        http_server = None
        feishu_wecom = [c for c in enabled if c.type in ("feishu", "wecom")]
        if feishu_wecom:
            http_server = self._start_http_server(port)

        for c in enabled:
            adapter = channels.create_adapter(c, on_message=None)
            if adapter is None:
                print(f"[gateway] 无法创建 adapter: {c.name} ({c.type})")
                continue
            # wire on_message: record origin chat->channel, then run agent
            orig_on_message = self.on_message

            def make_handler(ad):
                def handler(chat_id, text):
                    self._origin[chat_id] = ad.config.name
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

        try:
            if http_server:
                print(f"[gateway] webhook 服务器: http://0.0.0.0:{port}  (飞书/企微回调指到这里)")
            loop.run_forever()
        except KeyboardInterrupt:
            print("\n[gateway] 停止…")
        finally:
            for ad in self.adapters:
                ad.stop()
            if http_server:
                http_server.shutdown()
            loop.close()

    def _start_http_server(self, port: int) -> ThreadingHTTPServer:
        gate = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                pass  # silence

            def do_GET(self):
                # WeCom URL verification: echostr
                if self.path.startswith("/wecom"):
                    qs = dict(x.split("=", 1) for x in self.path.split("?", 1)[-1].split("&") if "=" in x)
                    echo = qs.get("echostr", "")
                    self._json({"errcode": 0, "errmsg": "ok", "echostr": echo})
                    return
                self._json({"ok": True, "service": "uiu gateway"})

            def do_POST(self):
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    body = json.loads(self.rfile.read(length).decode("utf-8"))
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
                    for ad in gate.adapters:
                        if ad.name == "wecom":
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

        server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server


def _build_tool_schemas(ws: Workspace) -> list[dict]:
    from . import tools
    schemas = tools.tool_defs()
    for skill in ws.skills:
        schemas.append(skill.to_tool_def())
    return schemas