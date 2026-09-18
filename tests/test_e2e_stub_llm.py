"""本地桩模型的端到端闭环（把「真 key E2E」变成平时也有人跑）。

审计 P1-12 的 `live` 用例默认跳过（要 key、要花钱、要联网），等于**日常无人验证整条链路**。
这里用一个几十行的 OpenAI 兼容桩服务器，在 CI 里真跑一遍：

    模型 → 工具 schema → tools.call_tool → 安全守卫 → 审计留痕 → 结果回灌 → 最终回答

不花钱、不联网、结果确定。真 key 的版本仍在 `test_e2e_live_llm.py`，
它验证的是「真实服务商的报文兼容性」，两者互补。
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest


def _chunk(delta: dict, finish: str | None = None, model: str = "stub-model") -> dict:
    return {"id": "chatcmpl-stub", "object": "chat.completion.chunk",
            "created": int(time.time()), "model": model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}


def _sse(payload: dict) -> bytes:
    return ("data: " + json.dumps(payload, ensure_ascii=False) + "\n\n").encode("utf-8")


def tool_call_script(call_id: str, name: str, args: dict) -> list[dict]:
    """把参数**拆成两片**发，验证 agent 端的分片拼装（真实服务商就是这么发的）。"""
    raw = json.dumps(args, ensure_ascii=False)
    head, tail = raw[: max(1, len(raw) // 2)], raw[max(1, len(raw) // 2):]
    return [
        _chunk({"role": "assistant", "tool_calls": [
            {"index": 0, "id": call_id, "type": "function",
             "function": {"name": name, "arguments": head}}]}),
        _chunk({"tool_calls": [{"index": 0, "function": {"arguments": tail}}]}),
        _chunk({}, finish="tool_calls"),
    ]


def text_script(*pieces: str) -> list[dict]:
    out = [_chunk({"role": "assistant", "content": p}) for p in pieces]
    out.append(_chunk({}, finish="stop"))
    return out


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"          # 响应结束即断开，SDK 读到 [DONE] 就停

    def do_POST(self):                     # noqa: N802
        length = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        body = json.loads(raw or b"{}")
        self.server.requests.append(body)  # type: ignore[attr-defined]

        script = self.server.script     # type: ignore[attr-defined]
        idx = min(len(self.server.requests) - 1, len(script) - 1)   # type: ignore[attr-defined]
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        for event in script[idx]:
            self.wfile.write(_sse(event))
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def log_message(self, *args):          # 静音
        return


class StubLLM:
    def __init__(self, script: list[list[dict]]):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.server.script = script        # type: ignore[attr-defined]
        self.server.requests = []          # type: ignore[attr-defined]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}/v1"

    @property
    def requests(self) -> list[dict]:
        return self.server.requests        # type: ignore[attr-defined]

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def stub():
    servers: list[StubLLM] = []

    def make(script):
        s = StubLLM(script)
        servers.append(s)
        return s

    yield make
    for s in servers:
        s.stop()


def _client(stub_server: StubLLM, monkeypatch):
    from uiu.config import ModelConfig
    from uiu.llm import make_client

    monkeypatch.setenv("OPENAI_API_KEY", "sk-stub-not-a-real-key")
    cfg = ModelConfig(provider="openai", default="stub-model",
                      base_url=stub_server.url, api_mode="chat_completions",
                      temperature=0.0, max_tokens=256,
                      api_key_env="OPENAI_API_KEY")
    return make_client(cfg), cfg


def _workspace(tmp_path: Path):
    from uiu.config import ensure_workspace
    from uiu.workspace import load_workspace

    ws_dir = tmp_path / "ws"
    ensure_workspace(ws_dir)
    return ws_dir, load_workspace(ws_dir)


def test_stub_model_drives_tool_then_answers(tmp_path, monkeypatch, stub):
    """整条链路：模型要工具 → 真执行 → 结果回灌 → 模型给最终回答。"""
    from uiu import tools
    from uiu.agent import run_turn
    from uiu.audit import read_events

    ws_dir, ws = _workspace(tmp_path)
    monkeypatch.setenv("UIU_WORKSPACE", str(ws_dir))
    server = stub([tool_call_script("call_1", "system_info", {}),
                   text_script("工具跑完了，", "答案是 OK。")])
    client, cfg = _client(server, monkeypatch)

    calls: list[tuple[str, dict]] = []
    results: list[tuple[str, str]] = []
    reply = run_turn(
        client=client,
        messages=[{"role": "system", "content": ws.system_prompt()},
                  {"role": "user", "content": "看看系统信息，然后只回复 OK。"}],
        tool_schemas=tools.tool_defs(),
        skills=[],
        model=cfg.default,
        cfg=cfg,
        on_tool_call=lambda name, args: calls.append((name, args)),
        on_tool_result=lambda name, out: results.append((name, out)),
    )

    # ① 最终回答来自第二轮
    assert "OK" in reply, reply
    # ② 工具真的被执行了
    assert [c[0] for c in calls] == ["system_info"], calls
    assert results and results[0][0] == "system_info"
    assert results[0][1] and "error" not in results[0][1].lower()[:40]
    # ③ 模型确实收到了工具 schema（注册表 → 模型这条路是通的）
    assert server.requests, "桩没收到请求"
    sent_tools = server.requests[0].get("tools") or []
    assert any(t["function"]["name"] == "system_info" for t in sent_tools), sent_tools[:3]
    # ④ 工具结果被回灌给模型（第二轮的 messages 里有 role=tool）
    assert len(server.requests) >= 2, server.requests
    second = server.requests[1]["messages"]
    tool_msgs = [m for m in second if m.get("role") == "tool"]
    assert tool_msgs, second[-3:]
    assert tool_msgs[0]["tool_call_id"] == "call_1"
    # ⑤ 全程留痕
    events = read_events(ws_dir, tail=50)
    assert any(e.get("tool") == "system_info" for e in events), [e.get("event") for e in events]


def test_stub_model_blocked_tool_never_runs(tmp_path, monkeypatch, stub):
    """安全守卫在真实回合里生效：破坏性命令被拦下，且模型收到的是 [blocked]。"""
    from uiu import tools
    from uiu.agent import run_turn
    from uiu.audit import read_events

    ws_dir, ws = _workspace(tmp_path)
    monkeypatch.setenv("UIU_WORKSPACE", str(ws_dir))
    # 用被判定为 BLOCKED 的形态（/etc 属系统目录）；即便守卫失效，Windows 上也没有 rm
    server = stub([tool_call_script("call_9", "shell_exec",
                                    {"command": "rm -rf /etc"}),
                   text_script("已被拦截。")])
    client, cfg = _client(server, monkeypatch)

    results: list[tuple[str, str]] = []
    reply = run_turn(
        client=client,
        messages=[{"role": "system", "content": ws.system_prompt()},
                  {"role": "user", "content": "删掉那个目录。"}],
        tool_schemas=tools.tool_defs(),
        skills=[],
        model=cfg.default,
        cfg=cfg,
        on_tool_result=lambda name, out: results.append((name, out)),
    )

    assert "拦截" in reply or "blocked" in reply.lower(), reply
    assert results, "工具结果应当回灌给模型"
    assert "[blocked]" in results[0][1], results[0][1]
    events = read_events(ws_dir, tail=50)
    blocked = [e for e in events if e.get("event") == "tool_blocked"]
    assert blocked, [e.get("event") for e in events]
    assert blocked[0].get("tool") == "shell_exec"


def test_stub_records_request_shape(tmp_path, monkeypatch, stub):
    """桩本身的自检：确认它收到的确实是标准 chat.completions 请求体（流式）。"""
    server = stub([text_script("h", "i")])
    client, cfg = _client(server, monkeypatch)
    stream = client.chat.completions.create(model=cfg.default,
                                            messages=[{"role": "user", "content": "hi"}],
                                            stream=True)
    text = "".join(c.choices[0].delta.content or "" for c in stream if c.choices)
    assert text == "hi"
    body = server.requests[0]
    assert body["model"] == "stub-model"
    assert body["messages"][0]["content"] == "hi"
    assert body["stream"] is True
