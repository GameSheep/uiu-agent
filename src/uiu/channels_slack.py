"""Slack adapter — slack-bolt Socket Mode (WebSocket 长连接，无需公网).

配置:
  SLACK_BOT_TOKEN=xoxb-...   # bot token
  SLACK_APP_TOKEN=xapp-...   # app-level token (scope: connections:write)
"""

from __future__ import annotations

import asyncio
import threading

from .channels import BaseChannelAdapter


class SlackAdapter(BaseChannelAdapter):
    name = "slack"

    def check(self) -> tuple[bool, str]:
        token = self.config.resolved_token()
        app_token = self.config.options.get("app_token", "")
        if not token:
            return False, "SLACK_BOT_TOKEN 未设置（uiu config --set-secret SLACK_BOT_TOKEN=xoxb-...）"
        if not app_token:
            return False, "缺少 app_token（channel add 时用 -o app_token=xapp-...）"
        return True, "✓ slack token 已设置（实际连接在 serve 时验证）"

    async def _listen(self) -> None:
        from slack_bolt import App
        from slack_bolt.adapter.socket_mode import SocketModeHandler

        token = self.config.resolved_token()
        app_token = self.config.options.get("app_token", "")
        queue: asyncio.Queue = asyncio.Queue()

        app = App(token=token)

        @app.event("message")
        def handle_message(event, say, logger):
            if event.get("subtype"):
                return  # ignore bot messages, message_changed, etc.
            text = event.get("text", "")
            channel = event.get("channel", "")
            if text and not text.startswith("!"):
                queue.put_nowait((channel, text))

        def _run():
            try:
                handler = SocketModeHandler(app, app_token)
                handler.start()
            except Exception as e:
                print(f"[slack] handler 异常: {e}", flush=True)

        t = threading.Thread(target=_run, daemon=True)
        t.start()

        while self._running:
            try:
                chat_id, text = await asyncio.wait_for(queue.get(), timeout=1.0)
                if self.on_message:
                    self.on_message(chat_id, text)
            except asyncio.TimeoutError:
                continue

    def send(self, chat_id: str, text: str) -> tuple[bool, str]:
        try:
            import urllib.request
            token = self.config.resolved_token()
            url = "https://slack.com/api/chat.postMessage"
            data = __import__("json").dumps({"channel": chat_id, "text": text}).encode("utf-8")
            req = urllib.request.Request(
                url, data=data,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = __import__("json").loads(resp.read().decode("utf-8"))
            return body.get("ok", False), "sent" if body.get("ok") else str(body)
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"