r"""真 LLM 最小闭环 E2E（审计 §6.3）。

默认**跳过**：只有同时满足「显式开启 UIU_E2E_LIVE=1」+「配置里能解析出 API key」才运行，
因为这会真实调用模型并产生费用。CI 不设这个变量，所以不会被误触发。

本地跑：
    $env:UIU_E2E_LIVE=1
    .venv\Scripts\python.exe -m pytest tests/test_e2e_live_llm.py -q -m live -s

验证的是**真实服务商**这条路：真模型 → 工具 schema → tools.call_tool → 安全守卫 → 审计留痕。

**没有 key 也能验证链路**：`tests/test_e2e_stub_llm.py` 用一个本地 OpenAI 兼容桩服务器，
在 CI 里跑同样的闭环（不花钱、不联网、结果确定）。本文件补的是「真实报文兼容性」这一层：
桩按我们**预期**的格式回，真服务商会不会那样回，只有跑过才知道。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

_MAX_TOKENS = 64


def _live_ready() -> tuple[bool, str]:
    if os.environ.get("UIU_E2E_LIVE", "").strip().lower() not in ("1", "true", "yes", "on"):
        return False, "未开启：设 UIU_E2E_LIVE=1（会真实调用模型并产生费用）"
    try:
        from uiu.config import AppConfig

        cfg = AppConfig()
    except Exception as exc:                     # noqa: BLE001
        return False, f"配置不可用: {exc}"
    if not cfg.model.resolved_api_key():
        return False, f"缺少 API key（{cfg.model.api_key_env or 'OPENAI_API_KEY'}）"
    return True, ""


_READY, _WHY = _live_ready()
pytestmark = [pytest.mark.live,
              pytest.mark.skipif(not _READY, reason="live E2E 跳过：" + _WHY)]


def _workspace(tmp_path: Path):
    from uiu.config import ensure_workspace
    from uiu.workspace import load_workspace

    ws_dir = tmp_path / "ws"
    ensure_workspace(ws_dir)
    return ws_dir, load_workspace(ws_dir)


def _client_and_cfg():
    from uiu.config import AppConfig
    from uiu.llm import make_client

    cfg = AppConfig()
    cfg.model.max_tokens = _MAX_TOKENS      # 成本上限：一次回合最多几十个 token
    cfg.model.temperature = 0
    return make_client(cfg.model), cfg.model


def test_live_plain_answer(tmp_path, monkeypatch):
    """最小闭环：真模型回一句话。"""
    from uiu.agent import run_turn

    ws_dir, ws = _workspace(tmp_path)
    monkeypatch.setenv("UIU_WORKSPACE", str(ws_dir))
    client, model_cfg = _client_and_cfg()

    chunks: list[str] = []
    reply = run_turn(
        client=client,
        messages=[{"role": "system", "content": ws.system_prompt()},
                  {"role": "user", "content": "只回复两个大写字母：OK。不要调用任何工具。"}],
        tool_schemas=[],
        skills=[],
        model=model_cfg.default,
        cfg=model_cfg,
        on_text=chunks.append,
    )
    assert reply and reply.strip(), "真模型没有返回内容"
    assert "OK" in reply.upper(), "回复不符合预期: " + reply[:120]
    assert "".join(chunks).strip(), "流式回调没有收到任何文本"


def test_live_tool_roundtrip(tmp_path, monkeypatch):
    """整条链路：模型决定调工具 → 守卫放行 → 真实执行 → 结果回填 → 审计留痕。"""
    from uiu import audit, tools
    from uiu.agent import run_turn

    ws_dir, ws = _workspace(tmp_path)
    monkeypatch.setenv("UIU_WORKSPACE", str(ws_dir))
    client, model_cfg = _client_and_cfg()

    used: list[str] = []
    results: list[tuple[str, str]] = []
    reply = run_turn(
        client=client,
        messages=[{"role": "system", "content": ws.system_prompt()},
                  {"role": "user",
                   "content": "请调用 shell_exec 执行命令 echo uiu-e2e-ok，然后原样告诉我输出。"}],
        tool_schemas=tools.tool_defs(),
        skills=[],
        model=model_cfg.default,
        cfg=model_cfg,
        on_tool_call=lambda name, args: used.append(name),
        on_tool_result=lambda name, res: results.append((name, res)),
    )

    assert "shell_exec" in used, "模型没有调用 shell_exec（used=%s）" % used
    assert any("uiu-e2e-ok" in (res or "") for _, res in results), results

    events = [e for e in audit.read_events(ws_dir, tail=50)
              if e.get("event") == "tool_call" and e.get("tool") == "shell_exec"]
    assert events, "工具执行没有写进审计日志"
    assert events[-1]["status"] == "ok"
    assert reply and reply.strip()
