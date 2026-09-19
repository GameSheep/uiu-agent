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


# --------------------------------------------------------------------------
# 网关启动契约：没起来就必须非 0（P0-5 同类）
# --------------------------------------------------------------------------


def test_serve_without_channels_fails_loudly(tmp_path, capsys):
    """没有 enabled channel 时网关压根没启动 —— 不能返回 0（否则脚本以为在跑）。"""
    from uiu.main import main

    ws = tmp_path / "ws"
    assert main(["--workspace", str(ws), "init"]) == 0
    capsys.readouterr()

    rc = main(["--workspace", str(ws), "serve", "--port", "8899"])
    captured = capsys.readouterr()
    assert rc != 0, "网关没启动却返回 0"
    assert "channel" in (captured.err + captured.out), captured


def test_serve_refuses_public_bind_without_token(tmp_path, monkeypatch, capsys):
    """对外监听且无 token 时必须拒绝启动，且明确说原因。"""
    from uiu.main import main

    ws = tmp_path / "ws"
    assert main(["--workspace", str(ws), "init"]) == 0
    capsys.readouterr()
    monkeypatch.delenv("UIU_GATEWAY_TOKEN", raising=False)
    monkeypatch.delenv("UIU_GATEWAY_INSECURE", raising=False)

    rc = main(["--workspace", str(ws), "serve", "--port", "8898", "--host", "0.0.0.0"])
    captured = capsys.readouterr()
    assert rc != 0, "对外监听无鉴权却放行"
    assert "token" in (captured.err + captured.out).lower(), captured


# --------------------------------------------------------------------------
# 网关鉴权：真实 HTTP 请求 + 拒绝必须留痕（面向网络的组件，审计要能回答「谁被拦下了」）
# --------------------------------------------------------------------------


@pytest.fixture
def live_gateway(tmp_path, monkeypatch):
    """真的起一个 HTTP server（端口 0 = 临时端口），跑完关掉。"""
    import threading

    from uiu.config import ensure_workspace, load_config
    from uiu.gateway import Gateway
    from uiu.workspace import load_workspace

    ws_dir = tmp_path / "gw"
    ensure_workspace(ws_dir)
    monkeypatch.setenv("UIU_GATEWAY_TOKEN", "test-token-xyz")
    gw = Gateway(load_config(ws_dir), load_workspace(ws_dir))
    # _start_http_server 内部已经起了 serve_forever 线程，这里不要再起一个
    server = gw._start_http_server(0, "127.0.0.1")
    port = server.server_address[1]
    try:
        yield f"http://127.0.0.1:{port}", ws_dir
    finally:
        server.shutdown()
        server.server_close()


def _live_get(url, token=None):
    """注意：不要叫 _get —— 本文件前面已有一个 _get(port, path, headers)，
    同名会把它覆盖掉（追加测试时踩过这个坑）。"""
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url)
    if token:
        req.add_header("X-Gateway-Token", token)
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def test_live_gateway_requires_and_accepts_the_token(live_gateway):
    base, _ = live_gateway
    status, body = _live_get(base + "/api/channels")
    assert status == 401, (status, body)
    status, body = _live_get(base + "/api/channels", token="wrong")
    assert status == 401, (status, body)
    status, body = _live_get(base + "/api/channels", token="test-token-xyz")
    assert status == 200, (status, body)
    assert "channels" in body


def test_live_gateway_health_endpoint_is_open(live_gateway):
    """健康响应不需要 token（否则监控探针也得持密钥）。"""
    base, _ = live_gateway
    status, body = _live_get(base + "/")
    assert status == 200 and "uiu gateway" in body, (status, body)


def test_gateway_auth_denials_are_audited(live_gateway):
    """被拒绝的请求必须留在审计里（含路径与来源），否则网络面等于没有取证能力。"""
    from uiu.audit import read_events

    base, ws_dir = live_gateway
    _live_get(base + "/api/channels")                 # 无 token
    _live_get(base + "/api/channels", token="bad")     # 错 token

    events = read_events(ws_dir, tail=50)
    denied = [e for e in events if e.get("event") == "gateway_auth_denied"]
    assert len(denied) >= 2, [e.get("event") for e in events]
    assert "/api/channels" in str(denied[0].get("path")), denied[0]
    assert denied[0].get("remote"), "拒绝事件没记来源地址"
