"""WeCom (企业微信) adapter — 自建应用回调 + 群机器人.

模式：企业微信自建应用接收消息回调（GET 验证 + POST 消息），回复走
message/send API（需要 access_token + agentid）。
群机器人（webhook）也可以：收到指令后用机器人 webhook 回复。

配置（channel add 时用 -o）:
  corpid=xxx  corpsecret=xxx  agentid=xxx
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
import urllib.request

from .channels import BaseChannelAdapter


class WeComAdapter(BaseChannelAdapter):
    name = "wecom"

    def __init__(self, config, on_message=None):
        super().__init__(config, on_message)
        self.corpid = self.config.options.get("corpid", "")
        self.corpsecret = self.config.options.get("corpsecret", "")
        self.agentid = self.config.options.get("agentid", "")
        self._token = None
        self._token_expires = 0
        self.queue: asyncio.Queue = asyncio.Queue()

    def _get_access_token(self) -> str:
        if self._token and time.time() < self._token_expires - 60:
            return self._token
        url = f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={self.corpid}&corpsecret={self.corpsecret}"
        data = self._http_get_json(url)
        if data.get("errcode") != 0:
            raise RuntimeError(f"gettoken failed: {data}")
        self._token = data["access_token"]
        self._token_expires = time.time() + (data.get("expires_in", 7200) or 7200)
        return self._token

    def check(self) -> tuple[bool, str]:
        if not self.corpid or not self.corpsecret:
            return False, "需要 corpid / corpsecret（channel add 时用 -o corpid=... corpsecret=...）"
        try:
            token = self._get_access_token()
        except Exception as e:
            return False, f"获取 token 失败: {type(e).__name__}: {e}"
        if not token:
            return False, "corpid/corpsecret 无效"
        return True, "✓ 企业微信凭据有效"

    async def _listen(self) -> None:
        while self._running:
            try:
                chat_id, text = await asyncio.wait_for(self.queue.get(), timeout=1.0)
                if self.on_message:
                    self.on_message(chat_id, text)
            except asyncio.TimeoutError:
                continue

    def handle_webhook(self, body: dict) -> dict:
        """Called by HTTP server when WeCom POSTs a callback."""
        if body.get("MsgType") == "text":
            chat_id = str(body.get("FromUserName", ""))  # userid for app messages
            text = body.get("Content", "")
            if text and self.on_message:
                self.on_message(chat_id, text)
        return {"errcode": 0, "errmsg": "ok"}

    def send(self, chat_id: str, text: str) -> tuple[bool, str]:
        try:
            token = self._get_access_token()
            data = self._http_post_json(
                f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}",
                {
                    "touser": chat_id,
                    "msgtype": "text",
                    "agentid": int(self.agentid) if self.agentid else 0,
                    "text": {"content": text},
                    "safe": 0,
                },
            )
            return data.get("errcode") == 0, "sent" if data.get("errcode") == 0 else str(data)
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"