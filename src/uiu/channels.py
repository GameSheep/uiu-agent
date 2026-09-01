"""Channel adapters: small functions that bridge external platforms to the agent.

Each adapter exposes:
    - test(channel_config) -> (ok: bool, message: str)

The actual *gateway* (long-running polling / webhook) is intentionally out of
scope for the skeleton — only token validation is here, so you can verify
credentials without spinning up a bot.

Add real gateway code later under e.g. uiu/gateway_telegram.py and wire it
into a `uiu serve` command.
"""

from __future__ import annotations

import urllib.request
import urllib.error
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import ChannelConfig


def test(c: "ChannelConfig") -> tuple[bool, str]:
    token = c.resolved_token()
    if not token:
        return False, f"{c.secret_env} not set"
    adapter = _ADAPTERS.get(c.type)
    if adapter is None:
        return False, f"unknown channel type: {c.type}"
    return adapter.test(token, c.options)


# ---------- telegram ----------

class _TelegramAdapter:
    def test(self, token: str, options: dict) -> tuple[bool, str]:
        url = f"https://api.telegram.org/bot{token}/getMe"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "uiu/0.1"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return False, f"HTTP {e.code}: unauthorized or invalid token"
        except urllib.error.URLError as e:
            return False, f"network error: {e.reason}"
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"

        if not data.get("ok"):
            return False, f"telegram api error: {data.get('description')}"

        bot = data["result"]
        return True, (
            f"✓ telegram bot reachable\n"
            f"  id:           {bot.get('id')}\n"
            f"  username:     @{bot.get('username')}\n"
            f"  first_name:   {bot.get('first_name')}\n"
            f"  can_join_groups: {bot.get('can_join_groups')}"
        )


_ADAPTERS: dict[str, object] = {
    "telegram": _TelegramAdapter(),
}


def supported_types() -> list[str]:
    return list(_ADAPTERS.keys())