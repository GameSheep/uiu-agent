"""Webhook validation without network: forged bodies must not drive the agent."""

from uiu.channels_feishu import FeishuAdapter
from uiu.channels_wecom import WeComAdapter
from uiu.config import ChannelConfig


def _cfg(**options):
    return ChannelConfig(type="t", name="n", options=options)


def test_feishu_wrong_token_rejected():
    ad = FeishuAdapter(_cfg(verify_token="secret"), on_message=None)
    body = {"header": {"event_type": "im.message.receive_v1"},
            "event": {"message": {"chat_id": "c", "message_type": "text", "content": "{}"}},
            "token": "forged"}
    assert ad.handle_webhook(body) == {"code": 1, "msg": "invalid token"}


def test_feishu_non_dict_rejected():
    ad = FeishuAdapter(_cfg(), on_message=None)
    assert ad.handle_webhook("nope")["code"] == 1  # type: ignore[arg-type]


def test_feishu_url_verification_passthrough():
    ad = FeishuAdapter(_cfg(verify_token="secret"), on_message=None)
    assert ad.handle_webhook({"type": "url_verification", "challenge": "ch"}) == {"challenge": "ch"}


def test_wecom_forged_empty_ignored():
    calls = []
    ad = WeComAdapter(_cfg(), on_message=lambda c, t: calls.append((c, t)))
    assert ad.handle_webhook({"MsgType": "text", "FromUserName": "", "Content": ""})["errcode"] == 0
    assert calls == []


def test_wecom_non_dict_rejected():
    ad = WeComAdapter(_cfg(), on_message=None)
    assert ad.handle_webhook([])["errcode"] == 1  # type: ignore[arg-type]


def test_wecom_valid_dispatched_with_caps():
    calls = []
    ad = WeComAdapter(_cfg(), on_message=lambda c, t: calls.append((c, t)))
    ad.handle_webhook({"MsgType": "text", "FromUserName": "u1", "Content": "hi"})
    assert calls == [("u1", "hi")]
