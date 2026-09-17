"""Generic webhook adapter — 任意系统 POST JSON 即变消息源。

网关路由：POST /generic/<channel名>，按 options 取字段：
  chat_field / text_field：body 中的 JSON 路径（点分隔，默认 chat_id / text）
  secret：必填，body.secret 或 ?secret= 须等于它（未配置则拒绝所有投递）

示例：
  uiu channel add ext --type webhook -o secret=xxx -o chat_field=user.id -o text_field=message
  curl POST :8765/generic/ext {"user":{"id":"u1"},"message":"hi","secret":"xxx"}
"""

from __future__ import annotations

import asyncio
import hmac

from .channels import BaseChannelAdapter


def _dig(body: dict, path: str):
    cur: object = body
    for part in (path or "").split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return ""
    return cur if isinstance(cur, (str, int)) else ""


class WebhookAdapter(BaseChannelAdapter):
    name = "webhook"

    def __init__(self, config, on_message=None):
        super().__init__(config, on_message)
        self.chat_field = self.config.options.get("chat_field", "chat_id")
        self.text_field = self.config.options.get("text_field", "text")
        self.secret = self.config.options.get("secret", "")
        self.queue: asyncio.Queue = asyncio.Queue()

    def check(self) -> tuple[bool, str]:
        if not self.secret:
            return False, ("✗ webhook 缺少 secret（等于开放投递口）："
                           "uiu channel add <name> --type webhook -o secret=<随机串>")
        return True, "✓ webhook 通道就绪（POST /generic/<name>，需 secret）"

    async def _listen(self) -> None:
        while self._running:
            try:
                chat_id, text = await asyncio.wait_for(self.queue.get(), timeout=1.0)
                if self.on_message:
                    self.on_message(chat_id, text)
            except asyncio.TimeoutError:
                continue

    def handle_webhook(self, body: dict, query_secret: str = "") -> dict:
        if not isinstance(body, dict):
            return {"code": 1, "msg": "bad body"}
        # secret 必填：通用 webhook 的 body 文本会直接进 agent，
        # 没有 secret 就是一个对外开放的「任意投递」入口。
        if not self.secret:
            return {"code": 1,
                    "msg": "webhook secret 未配置（拒绝投递）："
                           "uiu channel add <name> --type webhook -o secret=<随机串>"}
        got = str(body.get("secret", "") or query_secret or "")
        if not hmac.compare_digest(got, self.secret):
            return {"code": 1, "msg": "invalid secret"}
        chat_id = str(_dig(body, self.chat_field))[:128]
        text = str(_dig(body, self.text_field))[:20000]
        if chat_id and text.strip() and self.on_message:
            self.on_message(chat_id, text)
        return {"code": 0}

    def send(self, chat_id: str, text: str) -> tuple[bool, str]:
        # 出站 webhook：POST 到 options.callback（可选，用于双向系统）
        cb = self.config.options.get("callback", "")
        if not cb:
            return False, "webhook 无 callback（只进不出）"
        try:
            data = self._http_post_json(cb, {"chat_id": chat_id, "text": text})
            return True, str(data)[:200]
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"
