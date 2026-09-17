"""Gateway auth contract (audit P0-1).

网关能把任意入站文本喂给本机工具，所以「默认无鉴权 + 绑 0.0.0.0」等于对外交出执行权。
这里把安全默认值钉死：默认只绑本机、对外监听必须有 token、通用 webhook 必须有 secret。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from uiu import channels
from uiu.config import AppConfig, ChannelConfig
from uiu.gateway import Gateway, auth_status, resolve_bind
from uiu.workspace import Workspace


# --------------------------------------------------------------------------
# bind policy (pure)
# --------------------------------------------------------------------------


def test_loopback_is_the_default_bind(monkeypatch):
    monkeypatch.delenv("UIU_GATEWAY_HOST", raising=False)
    host, warnings = resolve_bind("", "")
    assert host == "127.0.0.1"
    assert warnings and "本机" in warnings[0], warnings


def test_public_bind_without_token_is_refused():
    with pytest.raises(RuntimeError) as exc:
        resolve_bind("0.0.0.0", "")
    msg = str(exc.value)
    assert "拒绝" in msg
    assert "UIU_GATEWAY_TOKEN" in msg
    assert "UIU_GATEWAY_INSECURE" in msg


def test_public_bind_with_token_is_allowed():
    host, warnings = resolve_bind("0.0.0.0", "tok")
    assert host == "0.0.0.0"
    assert warnings == []


def test_insecure_optin_is_explicit_and_warns(monkeypatch):
    monkeypatch.setenv("UIU_GATEWAY_INSECURE", "1")
    host, warnings = resolve_bind("0.0.0.0", "")
    assert host == "0.0.0.0"
    assert warnings and "INSECURE" in warnings[0] and "无鉴权" in warnings[0]


def test_host_env_is_honoured(monkeypatch):
    monkeypatch.setenv("UIU_GATEWAY_HOST", "127.0.0.1")
    assert resolve_bind("", "")[0] == "127.0.0.1"


def test_auth_status_text():
    assert "已启用" in auth_status("tok")
    assert "未启用" in auth_status("")


# --------------------------------------------------------------------------
# live HTTP surface
# --------------------------------------------------------------------------


def _gateway(tmp_path, monkeypatch, *, token: str = "", secret: str = "s3cr3t"):
    if token:
        monkeypatch.setenv("UIU_GATEWAY_TOKEN", token)
    else:
        monkeypatch.delenv("UIU_GATEWAY_TOKEN", raising=False)
    cfg = AppConfig()
    gw = Gateway(cfg, Workspace(root=tmp_path))
    captured: list[tuple[str, str]] = []
    if secret is not None:
        options = {"secret": secret, "chat_field": "user.id", "text_field": "message"}
    else:
        options = {"chat_field": "user.id", "text_field": "message"}
    adapter = channels.create_adapter(
        ChannelConfig(type="webhook", name="ext", options=options), on_message=None)
    adapter.on_message = lambda cid, text: captured.append((cid, text))
    gw.adapters.append(adapter)
    return gw, captured


def _post(port: int, path: str, body: dict, headers: dict | None = None):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _get(port: int, path: str, headers: dict | None = None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_api_and_generic_require_gateway_token(tmp_path, monkeypatch):
    gw, captured = _gateway(tmp_path, monkeypatch, token="tok-123")
    server = gw._start_http_server(0, "127.0.0.1")
    port = server.server_address[1]
    try:
        status, _ = _get(port, "/api/channels")
        assert status == 401, "带 token 时 /api/* 必须拒绝无 token 请求"

        status, _ = _get(port, "/api/channels", {"X-Gateway-Token": "wrong"})
        assert status == 401

        status, body = _get(port, "/api/channels", {"X-Gateway-Token": "tok-123"})
        assert status == 200 and "channels" in body

        status, _ = _post(port, "/generic/ext",
                          {"user": {"id": "u1"}, "message": "hi", "secret": "s3cr3t"})
        assert status == 401, "带 token 时 /generic/* 必须拒绝无 token 请求"

        status, body = _post(port, "/generic/ext",
                             {"user": {"id": "u1"}, "message": "hi", "secret": "s3cr3t"},
                             {"X-Gateway-Token": "tok-123"})
        assert status == 200 and body["code"] == 0, body
        assert captured == [("u1", "hi")]
    finally:
        server.shutdown()
        server.server_close()


def test_generic_webhook_rejects_wrong_secret(tmp_path, monkeypatch):
    gw, captured = _gateway(tmp_path, monkeypatch, token="tok-123")
    server = gw._start_http_server(0, "127.0.0.1")
    port = server.server_address[1]
    try:
        status, body = _post(port, "/generic/ext",
                             {"user": {"id": "u1"}, "message": "hi", "secret": "nope"},
                             {"X-Gateway-Token": "tok-123"})
        assert status == 200 and body["code"] == 1, body
        assert captured == [], "伪造 secret 的消息不能进 agent"
    finally:
        server.shutdown()
        server.server_close()


def test_startup_refuses_public_bind_without_token(tmp_path, monkeypatch):
    gw, _ = _gateway(tmp_path, monkeypatch, token="")
    with pytest.raises(RuntimeError):
        gw._start_http_server(0, "0.0.0.0")


def test_webhook_without_secret_is_rejected_locally(tmp_path):
    """通用 webhook 没配 secret 就是开放投递口 —— 必须在适配器层就拒绝。"""
    captured: list[tuple[str, str]] = []
    adapter = channels.create_adapter(
        ChannelConfig(type="webhook", name="ext", options={}),
        on_message=None)
    adapter.on_message = lambda cid, text: captured.append((cid, text))
    result = adapter.handle_webhook({"chat_id": "c", "text": "t"})
    assert result["code"] == 1
    assert "secret" in result["msg"]
    assert captured == []
    ok, msg = adapter.check()
    assert ok is False and "secret" in msg
