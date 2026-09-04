"""Email adapter — IMAP 轮询收件 + SMTP 发件（纯标准库，无新依赖）。

配置（channel add 时用 -o）:
  imap=smtp 例子：-o imap=imap.qq.com -o smtp=smtp.qq.com -o user=you@qq.com
  密码走 secret：uiu config --set-secret EMAIL_PASSWORD=xxx（secret_env 默认 EMAIL_PASSWORD）
  -o poll=60（轮询秒数） -o mailbox=INBOX -o from_filter=@company.com（可选发件人过滤）
chat_id 即发件人邮箱；回复即回邮件。
"""

from __future__ import annotations

import asyncio
import email
import email.header
import email.utils
import time

from .channels import BaseChannelAdapter


def _decode(h) -> str:
    parts = email.header.decode_header(h or "")
    out = []
    for data, enc in parts:
        if isinstance(data, bytes):
            out.append(data.decode(enc or "utf-8", errors="replace"))
        else:
            out.append(data)
    return "".join(out)


class EmailAdapter(BaseChannelAdapter):
    name = "email"

    def __init__(self, config, on_message=None):
        super().__init__(config, on_message)
        o = self.config.options
        self.imap = o.get("imap", "")
        self.smtp = o.get("smtp", "")
        self.user = o.get("user", "")
        self.mailbox = o.get("mailbox", "INBOX")
        self.from_filter = o.get("from_filter", "")
        try:
            self.poll = max(15, min(int(o.get("poll", 60)), 3600))
        except (TypeError, ValueError):
            self.poll = 60

    def _password(self) -> str:
        import os
        if self.config.secret_env:
            return os.environ.get(self.config.secret_env, "")
        return ""

    def check(self) -> tuple[bool, str]:
        if not self.imap or not self.user:
            return False, "需要 -o imap=... -o user=...（密码用 uiu config --set-secret EMAIL_PASSWORD=...）"
        import imaplib
        try:
            box = imaplib.IMAP4_SSL(self.imap, timeout=15)
            box.login(self.user, self._password())
            box.logout()
        except Exception as e:
            return False, f"IMAP 登录失败: {type(e).__name__}: {e}"
        return True, "✓ 邮箱凭据有效"

    async def _listen(self) -> None:
        import imaplib
        seen: set[str] = set()
        while self._running:
            try:
                box = imaplib.IMAP4_SSL(self.imap, timeout=30)
                box.login(self.user, self._password())
                box.select(self.mailbox)
                _, data = box.search(None, "UNSEEN")
                for num in data[0].split():
                    if num in seen:
                        continue
                    _, msg_data = box.fetch(num, "(RFC822)")
                    msg = email.message_from_bytes(msg_data[0][1])
                    sender = email.utils.parseaddr(msg.get("From", ""))[1]
                    if self.from_filter and self.from_filter not in sender:
                        continue
                    body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() == "text/plain" and not part.get_filename():
                                body = part.get_payload(decode=True).decode(
                                    part.get_content_charset() or "utf-8", errors="replace")
                                break
                    else:
                        body = msg.get_payload(decode=True).decode(errors="replace")
                    subject = _decode(msg.get("Subject", ""))
                    text = f"主题：{subject}\n{body.strip()}"[:20000]
                    seen.add(num)
                    if sender and text.strip() and self.on_message:
                        self.on_message(sender, text)
                box.close()
                box.logout()
            except Exception:
                pass
            for _ in range(self.poll):
                if not self._running:
                    return
                await asyncio.sleep(1)

    def send(self, chat_id: str, text: str) -> tuple[bool, str]:
        import smtplib
        import email.message
        if not self.smtp or not self.user:
            return False, "未配置 smtp/user"
        try:
            msg = email.message.EmailMessage()
            msg["From"] = self.user
            msg["To"] = chat_id
            msg["Subject"] = "Re: uiu"
            msg.set_content(text)
            with smtplib.SMTP_SSL(self.smtp, timeout=20) as s:
                s.login(self.user, self._password())
                s.send_message(msg)
            return True, "sent"
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"
