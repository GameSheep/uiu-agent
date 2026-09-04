"""WhatsApp Cloud API adapter — Meta 官方云接口（urllib，无新依赖）。

配置（channel add 时用 -o）:
  -o phone_id=123456789（Phone Number ID） -o verify=xxx（webhook 校验串）
token 走 secret：uiu config --set-secret WHATSAPP_TOKEN=...
收消息：Meta 回调 POST /whatsapp（需在 Meta 后台配回调 URL + verify token）。
"""

from __future__ import annotations

import asyncio

from .channels import BaseChannelAdapter


class WhatsAppAdapter(BaseChannelAdapter):
    name = "whatsapp"

    def __init__(self, config, on_message=None):
        super().__init__(config, on_message)
        self.phone_id = self.config.options.get("phone_id", "")
        self.verify = self.config.options.get("verify", "")
        self.queue: asyncio.Queue = asyncio.Queue()

    def _token(self) -> str:
        import os
        return os.environ.get(self.config.secret_env or "WHATSAPP_TOKEN", "")

    def check(self) -> tuple[bool, str]:
        if not self.phone_id or not self._token():
            return False, "需要 -o phone_id=... 且 uiu config --set-secret WHATSAPP_TOKEN=..."
        try:
            data = self._http_get_json(
                f"https://graph.facebook.com/v21.0/{self.phone_id}",
                headers={"Authorization": f"Bearer {self._token()}"})
        except Exception as e:
            return False, f"校验失败: {type(e).__name__}: {e}"
        if "error" in data:
            return False, f"token 无效: {data['error'].get('message', '')[:120]}"
        return True, f"✓ WhatsApp 就绪（{data.get('display_phone_number', '')}）"

    async def _listen(self) -> None:
        while self._running:
            try:
                chat_id, text = await asyncio.wait_for(self.queue.get(), timeout=1.0)
                if self.on_message:
                    self.on_message(chat_id, text)
            except asyncio.TimeoutError:
                continue

    def handle_webhook(self, body: dict) -> dict:
        if not isinstance(body, dict):
            return {"code": 1}
        try:
            for entry in body.get("entry", []):
                for change in entry.get("changes", []):
                    for msg in change.get("value", {}).get("messages", []):
                        if msg.get("type") != "text":
                            continue
                        chat_id = str(msg.get("from", ""))[:128]
                        text = str(msg.get("text", {}).get("body", ""))[:20000]
                        if chat_id and text.strip() and self.on_message:
                            self.on_message(chat_id, text)
        except Exception:
            pass
        return {"code": 0}

    def send(self, chat_id: str, text: str) -> tuple[bool, str]:
        try:
            data = self._http_post_json(
                f"https://graph.facebook.com/v21.0/{self.phone_id}/messages",
                {"messaging_product": "whatsapp", "to": chat_id,
                 "type": "text", "text": {"body": text[:4000]}},
                headers={"Authorization": f"Bearer {self._token()}"})
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"
        if "error" in data:
            return False, str(data["error"])[:200]
        return True, "sent"
