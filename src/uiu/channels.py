"""Channel adapters — Hermes-style platform plugin system (精简版).

Each adapter subclasses BaseChannelAdapter and implements:
    - check()    -> (ok, message)   verify credentials
    - start()    -> spawn background listener
    - stop()
    - send(chat_id, text)

Adapters live in uiu.channels (built-in) or ~/.uiu/channels/<name>/__init__.py
(user plugins, Hermes-style). Discovery is lazy + last-writer-wins.

The gateway (`uiu serve`) runs every enabled channel concurrently and routes
incoming messages to the agent loop, one conversation per chat_id.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from .config import ChannelConfig


class BaseChannelAdapter:
    """Base class for messaging platform adapters (Hermes BasePlatformAdapter)."""

    name: str = "base"

    def __init__(self, config: "ChannelConfig", on_message: Callable[[str, str], None] | None = None):
        self.config = config
        self.on_message = on_message  # (chat_id, text) -> None
        self._task: asyncio.Task | None = None
        self._running = False

    # -- required overrides -------------------------------------------
    def check(self) -> tuple[bool, str]:
        return False, "not implemented"

    async def _listen(self) -> None:
        """Background loop: poll for new messages, call self.on_message."""
        raise NotImplementedError

    def send(self, chat_id: str, text: str) -> tuple[bool, str]:
        raise NotImplementedError

    # -- lifecycle -----------------------------------------------------
    def start(self) -> None:
        self._running = True
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        self._task = loop.create_task(self._run())

    async def _run(self) -> None:
        try:
            await self._listen()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[{self.name}] listener error: {type(e).__name__}: {e}", file=sys.stderr)

    def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()

    # -- helpers -------------------------------------------------------
    def _http_get_json(self, url: str, headers: dict | None = None, timeout: int = 15) -> dict:
        req = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _http_post_json(self, url: str, payload: dict, headers: dict | None = None, timeout: int = 15) -> dict:
        data = json.dumps(payload).encode("utf-8")
        h = {"Content-Type": "application/json", **(headers or {})}
        req = urllib.request.Request(url, data=data, headers=h, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))


# ---------------------------------------------------------------------------
# Registry — Hermes-style lazy discovery + user plugin overrides
# ---------------------------------------------------------------------------

_ADAPTERS: dict[str, type[BaseChannelAdapter]] = {}
_discovered = False


def register_channel_adapter(adapter_cls: type[BaseChannelAdapter]) -> None:
    _ADAPTERS[adapter_cls.name] = adapter_cls


def get_adapter(name: str) -> type[BaseChannelAdapter] | None:
    _ensure_discovered()
    return _ADAPTERS.get(name)


def list_adapters() -> list[str]:
    _ensure_discovered()
    return sorted(_ADAPTERS)


def _user_channels_dir() -> Path | None:
    d = Path.home() / ".uiu" / "channels"
    return d if d.is_dir() else None


def _import_plugin_dir(plugin_dir: Path, source: str) -> None:
    init_file = plugin_dir / "__init__.py"
    if not init_file.exists():
        return
    module_name = f"_uiu_{source}_channel_{plugin_dir.name.replace('-', '_')}"
    if module_name in sys.modules:
        return
    try:
        spec = importlib.util.spec_from_file_location(
            module_name, init_file, submodule_search_locations=[str(plugin_dir)]
        )
        if spec is None or spec.loader is None:
            return
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    except Exception as exc:
        print(f"[channels] failed to load {source} plugin {plugin_dir.name}: {exc}", file=sys.stderr)
        sys.modules.pop(module_name, None)


def _ensure_discovered() -> None:
    global _discovered
    if _discovered:
        return
    _discovered = True
    # built-in adapters
    from .channels_telegram import TelegramAdapter
    from .channels_feishu import FeishuAdapter
    from .channels_wecom import WeComAdapter
    from .channels_dingtalk import DingTalkAdapter
    from .channels_discord import DiscordAdapter
    from .channels_slack import SlackAdapter
    register_channel_adapter(TelegramAdapter)
    register_channel_adapter(FeishuAdapter)
    register_channel_adapter(WeComAdapter)
    register_channel_adapter(DingTalkAdapter)
    register_channel_adapter(DiscordAdapter)
    register_channel_adapter(SlackAdapter)
    # user plugins (last-writer-wins)
    user_dir = _user_channels_dir()
    if user_dir is not None:
        for child in sorted(user_dir.iterdir()):
            if child.is_dir() and not child.name.startswith(("_", ".")):
                _import_plugin_dir(child, "user")


# ---------------------------------------------------------------------------
# Public API (used by `uiu channel` and `uiu serve`)
# ---------------------------------------------------------------------------

def check_channel(c: "ChannelConfig") -> tuple[bool, str]:
    """Verify a channel's credentials (Hermes: adapter.check)."""
    cls = get_adapter(c.type)
    if cls is None:
        return False, f"unknown channel type: {c.type} (supported: {', '.join(list_adapters())})"
    adapter = cls(c)
    return adapter.check()


def create_adapter(
    c: "ChannelConfig",
    on_message: Callable[[str, str], None] | None = None,
) -> BaseChannelAdapter | None:
    cls = get_adapter(c.type)
    if cls is None:
        return None
    return cls(c, on_message=on_message)


def supported_types() -> list[str]:
    return list_adapters()