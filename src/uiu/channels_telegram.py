"""Telegram adapter — Bot API long-polling.

- check: getMe (verify token)
- listen: getUpdates long-poll loop, feeds text messages to on_message
- send: sendMessage
"""

from __future__ import annotations

import asyncio
import json
import time
import urllib.request

from .channels import BaseChannelAdapter


class TelegramAdapter(BaseChannelAdapter):
    name = "telegram"

    def _api(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self.config.resolved_token()}/{method}"

    def check(self) -> tuple[bool, str]:
        try:
            data = self._http_get_json(self._api("getMe"))
        except urllib.error.HTTPError as e:
            return False, f"HTTP {e.code}: unauthorized or invalid token"
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"
        if not data.get("ok"):
            return False, f"telegram api error: {data.get('description')}"
        bot = data["result"]
        return True, (
            f"✓ telegram bot reachable\n"
            f"  id:       {bot.get('id')}\n"
            f"  username: @{bot.get('username')}"
        )

    async def _listen(self) -> None:
        offset = 0
        while self._running:
            try:
                url = self._api("getUpdates") + f"?timeout=25&offset={offset}"
                data = self._http_get_json(url, timeout=30)
            except Exception:
                await asyncio.sleep(3)
                continue
            for update in data.get("result", []):
                offset = update["update_id"] + 1
                msg = update.get("message") or update.get("edited_message")
                if not msg:
                    continue
                text = msg.get("text") or msg.get("caption")
                if not text:
                    continue
                chat_id = str(msg["chat"]["id"])
                # 透传给 gateway：slash 命令由 gateway.on_message 的注册表分发（与 TUI 同款），
                # 这里不做过滤，否则网关 slash 对 telegram 永不生效
                if self.on_message:
                    self.on_message(chat_id, text)

    def send(self, chat_id: str, text: str) -> tuple[bool, str]:
        try:
            data = self._http_post_json(
                self._api("sendMessage"),
                {"chat_id": int(chat_id), "text": text},
            )
            return data.get("ok", False), "sent" if data.get("ok") else str(data)
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"