"""Gateway bounds: session caps, input truncation, no-crash on empty input.

No network calls here: valid-text on_message would hit the LLM, so we only
exercise the guard paths + session eviction.
"""

from uiu.config import AppConfig
from uiu.gateway import Gateway
from uiu.workspace import Workspace


def _gw(tmp_path):
    cfg = AppConfig()
    ws = Workspace(root=tmp_path)
    return Gateway(cfg, ws)


def test_empty_message_no_crash(tmp_path):
    gw = _gw(tmp_path)
    gw.on_message("", "")
    gw.on_message("chat", "   ")
    assert gw.sessions == {}


def test_session_eviction_caps_memory(tmp_path):
    gw = _gw(tmp_path)
    gw.MAX_SESSIONS = 3
    for i in range(5):
        gw._session_messages(f"chat-{i}")
    assert len(gw.sessions) == 3
    assert "chat-0" not in gw.sessions


def test_origin_recorded_without_crash(tmp_path):
    gw = _gw(tmp_path)
    # simulate adapter wiring without starting anything
    class FakeAd:
        name = "telegram"

        class config:
            name = "tg-main"

    gw.adapters.append(FakeAd())
    gw._origin["c1"] = "tg-main"
    assert gw._origin_channel() == {"c1": "tg-main"}
