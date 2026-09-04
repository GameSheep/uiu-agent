"""内建 subagent 派发：在进程内跑独立 agent 循环（非外部 CLI）。

对齐 Hermes delegate_task 语义的最小版：
- delegate_task(task, tools=None, max_rounds=15)：隔离 messages + 可选工具白名单，返回子 agent 结论
- delegate_batch(tasks)：线程池并行跑多个，结果按序返回
- 上下文（client/cfg/ws/schemas）由宿主流程注入：delegation.set_context(...)
  TUI repl / gateway / cron runner 在启动时注入一次即可。
"""

from __future__ import annotations

import concurrent.futures
from dataclasses import dataclass
from typing import Any


@dataclass
class DelegationContext:
    client: Any
    cfg: Any          # ModelConfig
    ws: Any           # Workspace
    tool_schemas: list[dict]
    skills: list = None  # type: ignore[assignment]


_CTX: DelegationContext | None = None


def set_context(client, cfg, ws, tool_schemas: list[dict], skills: list | None = None) -> None:
    global _CTX
    _CTX = DelegationContext(client=client, cfg=cfg, ws=ws,
                             tool_schemas=tool_schemas, skills=skills if skills is not None else ws.skills)


def get_context() -> DelegationContext | None:
    return _CTX


def _filter_schemas(schemas: list[dict], allow: list[str] | None) -> list[dict]:
    if not allow:
        return schemas
    keep = set(allow)
    return [s for s in schemas if s.get("function", {}).get("name") in keep]


def delegate_task(task: str, tools: list[str] | None = None, max_rounds: int = 15) -> str:
    """Run an isolated subagent turn. `tools`: whitelist of tool names (None = all)."""
    ctx = get_context()
    if ctx is None:
        return "[error] delegation 上下文未初始化（宿主需先 delegation.set_context）"
    task = (task or "").strip()
    if not task:
        return "[error] task 不能为空"
    if len(task) > 20000:
        return "[error] task 过长（>20000）"
    try:
        max_rounds = max(1, min(int(max_rounds or 15), 30))
    except (TypeError, ValueError):
        return "[error] max_rounds 须为数字"

    from .agent import run_turn
    sub_schemas = _filter_schemas(ctx.tool_schemas, tools)
    messages = [
        {"role": "system",
         "content": ctx.ws.system_prompt() + "\n\n[你是子 agent：只专注完成下面这一个任务，完成后用中文给出结论，不要反问。]"},
        {"role": "user", "content": task},
    ]
    # 轮数上限：截断 schemas 传空则 run_turn 纯对话；用计数器包装 on_tool_call 熔断
    rounds = {"n": 0}

    def _count(name: str, args: dict) -> None:
        rounds["n"] += 1
        if rounds["n"] > max_rounds * 2:
            raise RuntimeError(f"子 agent 工具调用超限（>{max_rounds * 2}），强制结束")

    try:
        return run_turn(
            client=ctx.client, messages=messages,
            tool_schemas=sub_schemas, skills=ctx.skills,
            model=ctx.cfg.default, cfg=ctx.cfg,
            on_tool_call=_count,
        )
    except Exception as e:
        return f"[error] 子 agent 异常: {type(e).__name__}: {e}"


def delegate_batch(tasks: list[str], tools: list[str] | None = None, max_rounds: int = 15) -> str:
    """Run multiple subagent tasks in parallel threads, results in order."""
    if not tasks:
        return "[error] tasks 不能为空"
    if len(tasks) > 8:
        return "[error] 批量最多 8 个任务"
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(tasks), 8)) as pool:
        futs = [pool.submit(delegate_task, t, tools, max_rounds) for t in tasks]
        results = [f.result() for f in futs]
    out = []
    for i, r in enumerate(results, 1):
        out.append(f"## 任务{i}\n{r}")
    return "\n\n".join(out)


DELEGATE_TASK_DEF = {
    "type": "function",
    "function": {
        "name": "delegate_task",
        "description": "把子任务委派给内建子 agent（隔离上下文独立执行，适合独立可并行的子任务）。返回子 agent 的结论。",
        "parameters": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "子任务描述"},
                "tools": {"type": "array", "items": {"type": "string"},
                          "description": "允许子 agent 用的工具名白名单（可选，默认全部）"},
                "max_rounds": {"type": "integer", "description": "最大工具轮数（默认15，上限30）"},
            },
            "required": ["task"],
        },
    },
}

DELEGATE_BATCH_DEF = {
    "type": "function",
    "function": {
        "name": "delegate_batch",
        "description": "并行委派多个独立子任务（最多8个），按序返回各结论。",
        "parameters": {
            "type": "object",
            "properties": {
                "tasks": {"type": "array", "items": {"type": "string"}},
                "tools": {"type": "array", "items": {"type": "string"}},
                "max_rounds": {"type": "integer"},
            },
            "required": ["tasks"],
        },
    },
}

DELEGATION_TOOLS: dict[str, dict] = {
    "delegate_task": {"def": DELEGATE_TASK_DEF, "fn": delegate_task},
    "delegate_batch": {"def": DELEGATE_BATCH_DEF, "fn": delegate_batch},
}


def delegation_tool_defs() -> list[dict]:
    return [t["def"] for t in DELEGATION_TOOLS.values()]
