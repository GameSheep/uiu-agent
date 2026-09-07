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
        # 官方回调加密：配置 token + aes_key 后启用验签解密；否则明文兼容
        self.callback_token = self.config.options.get("token", "")
        self.encoding_aes_key = self.config.options.get("aes_key", "") or self.config.options.get("encoding_aes_key", "")
        self._token = None
        self._token_expires = 0
        self.queue: asyncio.Queue = asyncio.Queue()

    @property
    def crypto_enabled(self) -> bool:
        return bool(self.callback_token and self.encoding_aes_key)

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

    def verify_url(self, query: dict) -> dict:
        """WeCom GET URL verification: validate msg_signature, echo echostr.

        Only enforced when crypto is configured; otherwise the previous
        permissive behaviour is preserved for gateway-token-authenticated setups.
        """
        echo = query.get("echostr", "")
        if not echo:
            return {"errcode": 1, "errmsg": "no echostr"}
        if not self.crypto_enabled:
            return {"errcode": 0, "errmsg": "ok", "echostr": echo}
        from .wecom_crypto import verify_signature
        ok = verify_signature(
            self.callback_token, query.get("timestamp", ""),
            query.get("nonce", ""), echo, query.get("msg_signature", ""),
        )
        if not ok:
            return {"errcode": 1, "errmsg": "signature verify failed"}
        return {"errcode": 0, "errmsg": "ok", "echostr": echo}

    def handle_webhook(self, body: dict, query: dict | None = None) -> dict:
        """Called by HTTP server when WeCom POSTs a callback.

        When token + aes_key are configured, the official protocol is enforced:
        the body is `{"encrypt": ...}`, verified by msg_signature and decrypted
        with AES-CBC. Without crypto config we accept gateway-authenticated
        plaintext (legacy), still validating type/length.
        """
        query = query or {}
        if not isinstance(body, dict):
            return {"errcode": 1, "errmsg": "bad body"}
        # 官方加密模式：验签 + AES 解密
        if self.crypto_enabled:
            encrypt = body.get("encrypt", "")
            if not encrypt:
                return {"errcode": 1, "errmsg": "missing encrypt"}
            try:
                from .wecom_crypto import decrypt_encrypt_msg
                plain = decrypt_encrypt_msg(
                    encrypt, self.encoding_aes_key, self.corpid,
                    self.callback_token, query.get("timestamp", ""),
                    query.get("nonce", ""), query.get("msg_signature", ""),
                )
                body = json.loads(plain)
            except Exception as e:
                return {"errcode": 1, "errmsg": f"decrypt failed: {e}"}
        if not isinstance(body, dict):
            return {"errcode": 1, "errmsg": "bad body"}
        if body.get("MsgType") == "text":
            chat_id = str(body.get("FromUserName", ""))[:128]  # userid for app messages
            text = str(body.get("Content", ""))[:20000]
            if chat_id and text.strip() and self.on_message:
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