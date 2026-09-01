"""DingTalk (钉钉) adapter — Stream Mode (WebSocket 长连接，无需公网).

配置（channel add 时用 -o）:
  client_id=dingxxx     # 钉钉开放平台 app key / 机器人 Client ID
  client_secret=xxx     # app secret
"""

from __future__ import annotations

import asyncio
import json

from .channels import BaseChannelAdapter


class DingTalkAdapter(BaseChannelAdapter):
    name = "dingtalk"

    def __init__(self, config, on_message=None):
        super().__init__(config, on_message)
        self.client_id = self.config.options.get("client_id", "")
        self.client_secret = self.config.options.get("client_secret", "")

    # -- check -------------------------------------------------------
    def check(self) -> tuple[bool, str]:
        if not self.client_id or not self.client_secret:
            return False, "需要 client_id / client_secret（channel add 时用 -o client_id=... -o client_secret=...）"
        try:
            # 用 Stream 协议的 token 接口验证凭据
            import urllib.request
            url = "https://api.dingtalk.com/v1.0/oauth2/accessToken"
            data = json.dumps({
                "appKey": self.client_id,
                "appSecret": self.client_secret,
            }).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            if body.get("accessToken"):
                return True, "✓ 钉钉凭据有效"
            return False, f"凭据无效: {body}"
        except Exception as e:
            return False, f"验证失败: {type(e).__name__}: {e}"

    # -- listen ------------------------------------------------------
    async def _listen(self) -> None:
        import dingtalk_stream

        loop = asyncio.get_event_loop()
        received_queue: asyncio.Queue = asyncio.Queue()

        def on_message(msg: dict) -> None:
            """dingtalk_stream callback — push into asyncio queue."""
            try:
                data = msg.data if hasattr(msg, "data") else msg
                if isinstance(data, str):
                    data = json.loads(data)
                # 消息内容格式: {"senderStaffId":..., "text": {"content": "..."}, "conversationId": "cid..."}
                text = (data.get("text") or {}).get("content", "")
                conversation_id = data.get("conversationId", "")
                if text and conversation_id:
                    received_queue.put_nowait((conversation_id, text))
            except Exception:
                pass

        # register callback in the loop's executor context
        await loop.run_in_executor(None, self._start_stream, on_message)

        while self._running:
            try:
                chat_id, text = await asyncio.wait_for(received_queue.get(), timeout=1.0)
                if self.on_message:
                    self.on_message(chat_id, text)
            except asyncio.TimeoutError:
                continue

    def _start_stream(self, on_message) -> None:
        """Run dingtalk_stream client (blocking). Runs in executor thread."""
        import dingtalk_stream
        from dingtalk_stream import AckMessage

        class Handler(dingtalk_stream.ChatbotHandler):
            async def process(self, callback: dingtalk_stream.CallbackMessage):
                on_message(callback.data)
                return AckMessage.STATUS_OK, "OK"

        client = dingtalk_stream.DingTalkStreamClient(
            credential=dingtalk_stream.Credential(self.client_id, self.client_secret),
        )
        client.register_callback_handler(
            dingtalk_stream.ChatbotMessage.TOPIC,
            Handler()
        )
        client.start_forever()

    # -- send --------------------------------------------------------
    def send(self, chat_id: str, text: str) -> tuple[bool, str]:
        try:
            # 钉钉机器人发消息（Stream 模式用 /v1.0/robot/oToMessages/batchSend 或 groupMessages/send）
            # 简化：用机器人单聊发送接口
            import urllib.request
            # 先拿 access token
            token_url = "https://api.dingtalk.com/v1.0/oauth2/accessToken"
            data = json.dumps({"appKey": self.client_id, "appSecret": self.client_secret}).encode("utf-8")
            req = urllib.request.Request(token_url, data=data, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                token = json.loads(resp.read().decode("utf-8")).get("accessToken", "")

            # 群消息（conversationId 是 cid）
            url = "https://api.dingtalk.com/v1.0/robot/groupMessages/send"
            payload = {
                "msgParam": json.dumps({"content": text}),
                "msgKey": "sampleText",
                "openConversationId": chat_id,
            }
            req = urllib.request.Request(
                url, data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json", "x-acs-dingtalk-access-token": token},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            return True, "sent" if "processQueryKey" in body or "processCode" in body else str(body)
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"