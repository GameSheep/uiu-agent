"""Discord adapter — discord.py gateway (WebSocket 长连接，单 token，无需公网).

配置: DISCORD_BOT_TOKEN（Discord Developer Portal 建 bot 拿 token）。
"""

from __future__ import annotations

import asyncio
import threading

from .channels import BaseChannelAdapter


class DiscordAdapter(BaseChannelAdapter):
    name = "discord"

    def check(self) -> tuple[bool, str]:
        token = self.config.resolved_token()
        if not token:
            return False, "DISCORD_BOT_TOKEN 未设置（uiu config --set-secret DISCORD_BOT_TOKEN=...）"
        return True, "✓ discord token 已设置（实际连接在 serve 时验证）"

    async def _listen(self) -> None:
        import discord
        import discord.ext.commands as commands

        token = self.config.resolved_token()
        queue: asyncio.Queue = asyncio.Queue()

        intents = discord.Intents.default()
        intents.message_content = True

        bot = commands.Bot(command_prefix="!", intents=intents)

        @bot.event
        async def on_ready():
            print(f"[discord] 已连接: {bot.user}", flush=True)

        @bot.event
        async def on_message(message):
            if message.author == bot.user:
                return
            if message.content.startswith("!"):
                return
            # 只处理 DM 或 @bot 的消息
            if isinstance(message.channel, discord.DMChannel) or bot.user in message.mentions:
                # strip mention
                text = message.content.replace(f"<@{bot.user.id}>", "").strip()
                if text:
                    queue.put_nowait((str(message.channel.id), text))

        # run bot in a thread (discord.py manages its own loop)
        def _run():
            try:
                bot.run(token)
            except Exception as e:
                print(f"[discord] bot.run 异常: {e}", flush=True)

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
        # discord.py bot 实例在 _listen 的线程里；这里用 REST webhook 或暂存。
        # 简化：通过 bot 的 fetch_channel 是 async 的，这里只能异步——gateway 里
        # 我们同步调用 send。用 create_task 把发送排进 bot 的 loop。
        try:
            import discord
            token = self.config.resolved_token()
            # 用纯 REST：POST /channels/{id}/messages（无需 bot 实例）
            import urllib.request
            url = f"https://discord.com/api/v10/channels/{chat_id}/messages"
            data = __import__("json").dumps({"content": text}).encode("utf-8")
            req = urllib.request.Request(
                url, data=data,
                headers={"Authorization": f"Bot {token}", "Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                return True, "sent"
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"