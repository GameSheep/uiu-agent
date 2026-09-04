"""Feishu (飞书/Lark) adapter — 自建应用, 长连接或 webhook 模式.

Feishu 有事件订阅机制（im.message.receive_v1）。自建应用推荐用长连接
（ws）或 webhook（HTTP 回调）。这里实现最稳的 webhook 模式：
- 需要配置 FEISHU_APP_ID / FEISHU_APP_SECRET / FEISHU_VERIFY_TOKEN
- 用户加机器人后，私聊/群聊消息通过 webhook 进来
- 回复走 im/v1/messages API（需要 tenant_access_token）

注意：webhook 需要公网地址（或内网穿透）。本地开发可用长连接模式。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
import urllib.request

from .channels import BaseChannelAdapter


class FeishuAdapter(BaseChannelAdapter):
    name = "feishu"

    def __init__(self, config, on_message=None):
        super().__init__(config, on_message)
        self.app_id = self.config.options.get("app_id", "")
        self.app_secret = self.config.options.get("app_secret", "")
        self.verify_token = self.config.options.get("verify_token", "")
        self._tenant_token = None
        self._token_expires = 0
        self.queue: asyncio.Queue = asyncio.Queue()

    # -- helpers ------------------------------------------------------
    def _get_tenant_token(self) -> str:
        """Fetch tenant_access_token (2h validity, cached)."""
        if self._tenant_token and time.time() < self._token_expires - 60:
            return self._tenant_token
        data = self._http_post_json(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            {"app_id": self.app_id, "app_secret": self.app_secret},
        )
        self._tenant_token = data.get("tenant_access_token", "")
        self._token_expires = time.time() + (data.get("expire", 7200) or 7200)
        return self._tenant_token

    # -- required -----------------------------------------------------
    def check(self) -> tuple[bool, str]:
        if not self.app_id or not self.app_secret:
            return False, "需要 FEISHU_APP_ID / FEISHU_APP_SECRET（channel add 时用 -o app_id=... app_secret=...）"
        try:
            token = self._get_tenant_token()
        except Exception as e:
            return False, f"获取 token 失败: {type(e).__name__}: {e}"
        if not token:
            return False, "app_id/app_secret 无效"
        return True, "✓ 飞书应用凭据有效"

    async def _listen(self) -> None:
        # webhook 模式：adapter 不主动轮询，由 serve 命令启动 HTTP server
        # 把收到的消息从 queue 取出交给 on_message。
        while self._running:
            try:
                chat_id, text = await asyncio.wait_for(self.queue.get(), timeout=1.0)
                if self.on_message:
                    self.on_message(chat_id, text)
            except asyncio.TimeoutError:
                continue

    def handle_webhook(self, body: dict) -> dict:
        """Called by the HTTP server when Feishu POSTs an event.
        Returns the verification response when needed."""
        import hmac
        if not isinstance(body, dict):
            return {"code": 1, "msg": "bad body"}
        if body.get("type") == "url_verification":
            return {"challenge": body.get("challenge")}
        if self.verify_token:
            # 常量时间比较，防时序攻击；未配置 token 时由网关层 UIU_GATEWAY_TOKEN 鉴权
            if not hmac.compare_digest(str(body.get("token", "")), self.verify_token):
                return {"code": 1, "msg": "invalid token"}
        header = body.get("header", {})
        if header.get("event_type") != "im.message.receive_v1":
            return {"code": 0}
        event = body.get("event", {})
        message = event.get("message", {})
        chat_id = str(message.get("chat_id", ""))
        msg_type = message.get("message_type", "")
        content = message.get("content", "{}")
        text = ""
        try:
            if msg_type == "text":
                text = json.loads(content).get("text", "")
            elif msg_type == "post":
                # rich text: 提取纯文本
                post = json.loads(content).get("content", [])
                parts = []
                for line in post:
                    for seg in line:
                        if isinstance(seg, dict) and seg.get("tag") == "text":
                            parts.append(seg.get("text", ""))
                text = "".join(parts)
        except Exception:
            text = ""
        if text and self.on_message:
            self.on_message(chat_id, text)
        return {"code": 0}

    def send(self, chat_id: str, text: str) -> tuple[bool, str]:
        try:
            token = self._get_tenant_token()
            data = self._http_post_json(
                f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
                {
                    "receive_id": chat_id,
                    "msg_type": "text",
                    "content": json.dumps({"text": text}),
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            return data.get("code", 1) == 0, "sent" if data.get("code") == 0 else str(data)
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"