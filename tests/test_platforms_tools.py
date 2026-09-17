"""New platforms + tools: webhook/email/whatsapp, proc, clarify, browser, skills disclosure."""

import sys


def _cfg(ctype, name="t", **options):
    from uiu.config import ChannelConfig
    return ChannelConfig(type=ctype, name=name, options=options)


def test_webhook_secret_and_digging():
    from uiu.channels_webhook import WebhookAdapter
    calls = []
    ad = WebhookAdapter(_cfg("webhook", chat_field="user.id", text_field="message",
                             secret="s3cr3t"), on_message=lambda c, t: calls.append((c, t)))
    assert ad.handle_webhook({"user": {"id": "u1"}, "message": "hi"})["code"] == 1
    assert calls == []
    assert ad.handle_webhook({"user": {"id": "u1"}, "message": "hi", "secret": "s3cr3t"})["code"] == 0
    assert calls == [("u1", "hi")]


def test_webhook_without_secret_is_rejected():
    """P0-1：通用 webhook 会把 body 文本直接喂给 agent，没 secret 就是开放入口。"""
    from uiu.channels_webhook import WebhookAdapter
    calls = []
    ad = WebhookAdapter(_cfg("webhook"), on_message=lambda c, t: calls.append((c, t)))
    result = ad.handle_webhook({"chat_id": "c", "text": "t"})
    assert result["code"] == 1
    assert "secret" in result["msg"]
    assert calls == []


def test_whatsapp_dispatch_and_noise_ignored():
    from uiu.channels_whatsapp import WhatsAppAdapter
    calls = []
    ad = WhatsAppAdapter(_cfg("whatsapp"), on_message=lambda c, t: calls.append((c, t)))
    body = {"entry": [{"changes": [{"value": {"messages": [
        {"type": "text", "from": "86138", "text": {"body": "你好"}},
        {"type": "image", "from": "86138"},
    ]}}]}]}
    assert ad.handle_webhook(body)["code"] == 0
    assert calls == [("86138", "你好")]
    assert ad.handle_webhook([])["code"] == 1


def test_proc_run_log_list(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from uiu import proc_tools as P
    pid = P.proc_run("echo hello-proc")
    assert pid.startswith("[ok]"), pid
    ident = pid.split()[1]
    import time
    for _ in range(50):
        log = P.proc_log(ident)
        if "hello-proc" in log:
            break
        time.sleep(0.1)
    assert "hello-proc" in log, log
    assert ident in P.proc_list()
    assert P.proc_kill("nope").startswith("[error]")


def test_clarify_without_host():
    from uiu import clarify as C
    C.set_ask_handler(None)
    out = C.clarify("继续吗？", ["要", "不要"])
    assert "继续吗" in out and "要" in out


def test_clarify_with_handler():
    from uiu import clarify as C
    C.set_ask_handler(lambda q, o: "要")
    try:
        assert C.clarify("继续吗？") == "要"
    finally:
        C.set_ask_handler(None)
    assert C.clarify("").startswith("[error]")


def test_browser_guards():
    from uiu import browser_tools as B
    assert B.browser_navigate("javascript:alert(1)").startswith("[error]")
    assert B.browser_click("").startswith("[error]")
    assert B.browser_fill("", "x").startswith("[error]")
    # playwright 未装时给出安装指引而非崩溃
    if "playwright" not in sys.modules:
        try:
            __import__("playwright")
            has_pw = True
        except ImportError:
            has_pw = False
        if not has_pw:
            assert "playwright" in B.browser_snapshot()


def test_skills_disclosure_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("UIU_WORKSPACE", str(tmp_path / "ws"))
    ws = tmp_path / "ws" / "skills" / "demo"
    ws.mkdir(parents=True)
    (ws / "SKILL.md").write_text(
        "---\nname: demo\ndescription: 演示技能\n---\n\nexec: echo\n", encoding="utf-8")
    from uiu.skills_runtime import skill_view, skills_list
    assert "demo" in skills_list()
    assert "演示技能" in skill_view("demo")
    assert skill_view("nope").startswith("[error]")
    assert skill_view("").startswith("[error]")


def test_web_search_parses_single_quote_markup(monkeypatch):
    # DDG lite 用单引号 + href 在 class 之前——回归：必须解析出来（离线 canned HTML）
    import uiu.web_tools as W
    html = (
        '<a rel="nofollow" href="https://www.python.org/"'
        " class='result-link'>Welcome to Python.org</a>"
        "<tr><td class='result-snippet'>popular language</td></tr>"
    )
    monkeypatch.setattr(W, "_http", lambda *a, **k: (html.encode(), "text/html"))
    out = W.web_search("python", count=5)
    assert "Welcome to Python.org" in out and "https://www.python.org/" in out
    assert "popular language" in out


def test_web_search_validates_input():
    from uiu.web_tools import web_search
    assert web_search("").startswith("[error]")
    assert web_search("x" * 501).startswith("[error]")
