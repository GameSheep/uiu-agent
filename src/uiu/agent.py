"""Agent loop: chat with tool calling, streaming.

This is the heart of the skeleton. It:
1. Maintains a single rolling conversation (list[dict]).
2. Calls the LLM with streaming.
3. If the model emits tool_calls, executes them (locally) and feeds results back.
4. Loops until the model emits a final text reply (no more tool_calls).
"""

from __future__ import annotations

import json
import sys
from typing import Callable, Iterator

from openai import OpenAI

from . import tools
from .llm import get_model, stream_chat, _create
from .config import ModelConfig


# ---------- non-streaming call (used to drive tool-use loop) ----------

def _trim_messages(messages: list[dict], max_chars: int = 120_000) -> list[dict]:
    """Keep conversation within budget: uses intelligent rolling state compaction,
    preserving root intent, structured action checkpoints, and recent detailed turns.
    """
    try:
        from .context_compressor import compact_conversation_history
        return compact_conversation_history(messages, max_chars=max_chars)
    except Exception:
        pass

    # Fast path: small enough
    total = sum(len(m.get("content", "")) if isinstance(m.get("content"), str) else 400 for m in messages)
    if total <= max_chars:
        return messages
    # Keep system + newest; drop oldest pairs until under budget
    kept: list[dict] = []
    used = 0
    for m in reversed(messages):
        cost = len(m["content"]) if isinstance(m["content"], str) else 400
        if m.get("role") == "system":
            kept.insert(0, m)
            used += cost
            continue
        if used + cost > max_chars and kept:
            continue  # drop this older turn
        kept.insert(0, m)
        used += cost
    return kept



def _call_once(
    client: OpenAI,
    messages: list[dict],
    tool_schemas: list[dict],
    model: str,
    cfg: ModelConfig | None = None,
) -> dict:
    """One non-streaming chat.completions.create call; returns the assistant message dict."""
    if cfg is not None and cfg.api_mode == "anthropic_messages":
        # anthropic path: tool calls come back differently
        from anthropic import Anthropic
        from .llm import _to_anthropic_messages
        sys_msgs = [m["content"] for m in messages if m.get("role") == "system"]
        user_msgs = [m for m in messages if m.get("role") != "system"]
        system = "\n\n".join(sys_msgs) or None
        tool_defs = None
        if tool_schemas:
            tool_defs = []
            for t in tool_schemas:
                f = t.get("function", {})
                tool_defs.append({
                    "name": f.get("name"),
                    "description": f.get("description", ""),
                    "input_schema": f.get("parameters", {"type": "object", "properties": {}}),
                })
        resp = client.messages.create(
            model=model,
            system=system,
            messages=_to_anthropic_messages(user_msgs),
            max_tokens=cfg.max_tokens or 4096,
            tools=tool_defs or None,
        )
        out: dict = {"role": "assistant", "content": ""}
        tool_calls = []
        for block in resp.content:
            if block.type == "text":
                out["content"] += block.text
            elif block.type == "tool_use":
                tool_calls.append({
                    "id": block.id,
                    "type": "function",
                    "function": {"name": block.name, "arguments": json.dumps(block.input)},
                })
        if tool_calls:
            out["tool_calls"] = tool_calls
        return out

    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        tools=tool_schemas or None,
        tool_choice="auto" if tool_schemas else None,
    )
    msg = resp.choices[0].message
    out: dict = {"role": "assistant", "content": msg.content or ""}
    if msg.tool_calls:
        out["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            for tc in msg.tool_calls
        ]
    return out


# ---------- streaming call (tokens out as they arrive) ----------

def _assemble_openai_tool_calls(tc_acc: dict) -> list[dict]:
    out = []
    for idx in sorted(tc_acc):
        e = tc_acc[idx]
        out.append({
            "id": e.get("id") or f"call_{idx}",
            "type": "function",
            "function": {"name": e.get("name") or "", "arguments": e.get("args") or "{}"},
        })
    return out


def _call_once_stream(
    client: OpenAI,
    messages: list[dict],
    tool_schemas: list[dict],
    model: str,
    cfg: ModelConfig | None = None,
    on_text: Callable[[str], None] | None = None,
    on_thought: Callable[[str], None] | None = None,
) -> dict:
    """One chat call with streaming; text deltas go to on_text live, thought deltas to on_thought.

    Returns the assistant message dict (same shape as _call_once).
    """
    if cfg is not None and cfg.api_mode == "anthropic_messages":
        from .llm import _to_anthropic_messages
        sys_msgs = [m["content"] for m in messages if m.get("role") == "system"]
        user_msgs = [m for m in messages if m.get("role") != "system"]
        system = "\n\n".join(sys_msgs) or None
        tool_defs = None
        if tool_schemas:
            tool_defs = []
            for t in tool_schemas:
                f = t.get("function", {})
                tool_defs.append({
                    "name": f.get("name"),
                    "description": f.get("description", ""),
                    "input_schema": f.get("parameters", {"type": "object", "properties": {}}),
                })
        kwargs: dict = {
            "model": model,
            "system": system,
            "messages": _to_anthropic_messages(user_msgs),
            "max_tokens": cfg.max_tokens or 4096,
        }
        if tool_defs:
            kwargs["tools"] = tool_defs
        with client.messages.stream(**kwargs) as s:
            for text in s.text_stream:
                if text and on_text:
                    on_text(text)
            final = s.get_final_message()
        out: dict = {"role": "assistant", "content": ""}
        tool_calls = []
        for block in final.content:
            if block.type == "text":
                out["content"] += block.text
            elif block.type == "thinking":
                if on_thought and hasattr(block, "thinking"):
                    on_thought(block.thinking)
            elif block.type == "tool_use":
                tool_calls.append({
                    "id": block.id,
                    "type": "function",
                    "function": {"name": block.name, "arguments": json.dumps(block.input)},
                })
        if tool_calls:
            out["tool_calls"] = tool_calls
        return out

    stream = client.chat.completions.create(
        model=model,
        messages=messages,
        tools=tool_schemas or None,
        tool_choice="auto" if tool_schemas else None,
        stream=True,
        timeout=300,
    )
    content_parts: list[str] = []
    tc_acc: dict[int, dict] = {}
    in_think_tag = False
    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if delta is None:
            continue

        # 1. Native reasoning_content (DeepSeek-R1 / V3 / Qwen / etc.)
        thought_piece = getattr(delta, "reasoning_content", None)
        if not thought_piece and hasattr(delta, "model_extra") and delta.model_extra:
            thought_piece = delta.model_extra.get("reasoning_content")
        if thought_piece:
            if on_thought:
                on_thought(thought_piece)

        # 2. Content piece (with inline <think> tag handling)
        piece = getattr(delta, "content", None)
        if piece:
            content_parts.append(piece)
            if "<think>" in piece or "</think>" in piece or in_think_tag:
                remaining = piece
                while remaining:
                    if not in_think_tag:
                        if "<think>" in remaining:
                            pre, post = remaining.split("<think>", 1)
                            if pre and on_text:
                                on_text(pre)
                            in_think_tag = True
                            remaining = post
                        else:
                            if on_text:
                                on_text(remaining)
                            remaining = ""
                    else:
                        if "</think>" in remaining:
                            th, post = remaining.split("</think>", 1)
                            if th and on_thought:
                                on_thought(th)
                            in_think_tag = False
                            remaining = post
                        else:
                            if on_thought:
                                on_thought(remaining)
                            remaining = ""
            else:
                if on_text:
                    on_text(piece)

        # 3. Tool calls
        for tc in getattr(delta, "tool_calls", None) or []:
            e = tc_acc.setdefault(tc.index, {"id": "", "name": "", "args": ""})
            if getattr(tc, "id", None):
                e["id"] = tc.id
            fn = getattr(tc, "function", None)
            if fn is not None:
                if getattr(fn, "name", None):
                    e["name"] = fn.name
                if getattr(fn, "arguments", None):
                    e["args"] += fn.arguments
    out = {"role": "assistant", "content": "".join(content_parts)}
    if tc_acc:
        out["tool_calls"] = _assemble_openai_tool_calls(tc_acc)
    return out


# ---------- public API ----------

def _cap_result(result: str, limit: int = 4000) -> str:
    """Trim an over-long tool result, keeping the head and tail (where errors live)."""
    if isinstance(result, str) and len(result) > limit:
        return result[: limit - 200] + f"\n…[truncated {len(result) - limit} chars]…\n" + result[-200:]
    return result


def repair_tool_sequence(messages: list[dict]) -> list[dict]:
    """Drop orphan tool messages / demote assistant turns with no tool results.

    Keeps chat_completions history valid: every `tool` msg must directly answer
    a preceding assistant `tool_calls`, and every assistant `tool_calls` must be
    followed by its tool results. Protects against trimmed/legacy histories
    (e.g. sessions saved before tool_calls were preserved).
    """
    out: list[dict] = []
    i, n = 0, len(messages)
    while i < n:
        m = messages[i]
        if m.get("role") == "assistant" and m.get("tool_calls"):
            calls = [tc for tc in m["tool_calls"] if isinstance(tc, dict)]
            ids = [tc.get("id") for tc in calls]
            j = i + 1
            tool_msgs = []
            while j < n and messages[j].get("role") == "tool":
                tool_msgs.append(messages[j])
                j += 1
            have = {t.get("tool_call_id") for t in tool_msgs}
            if all(cid in have for cid in ids):
                out.append(m)
                out.extend(tool_msgs)
            elif tool_msgs:
                keep = [t for t in tool_msgs if t.get("tool_call_id") in set(ids)]
                kept_calls = [tc for tc in calls if tc.get("id") in have]
                m2 = dict(m, tool_calls=kept_calls)
                out.append(m2)
                out.extend(keep)
            else:
                m2 = {k: v for k, v in m.items() if k != "tool_calls"}
                if m2.get("content"):
                    out.append(m2)
            i = j
        elif m.get("role") == "tool":
            i += 1  # orphan tool result — drop instead of 400
        else:
            out.append(m)
            i += 1
    return out


_TRANSIENT_HINTS = ("429", "500", "502", "503", "504", "timeout", "timed out",
                    "connection", "overloaded", "try again", "temporarily")


def _is_transient(err: Exception) -> bool:
    name = type(err).__name__.lower()
    if name in ("apiconnectionerror", "apitimeouterror", "ratelimitererror",
                "internalservererror", "serviceunavailableerror", "timeouterror"):
        return True
    msg = str(err).lower()
    return any(h in msg for h in _TRANSIENT_HINTS)


def _is_context_overflow(err: Exception) -> bool:
    msg = str(err).lower()
    return "context_length" in msg or "maximum context" in msg or "context limit" in msg


def run_turn(
    client: OpenAI,
    messages: list[dict],
    tool_schemas: list[dict],
    skills: list | None = None,
    model: str = "",
    cfg: ModelConfig | None = None,
    on_text: Callable[[str], None] | None = None,
    on_thought: Callable[[str], None] | None = None,
    on_tool_call: Callable[[str, dict], None] | None = None,
    on_tool_result: Callable[[str, str], None] | None = None,
    on_notice: Callable[[str], None] | None = None,
) -> str:
    """Run a single user turn (may involve multiple LLM round-trips for tool use).

    Text streams token-by-token via on_text, thought deltas via on_thought.
    Calls on_tool_call(name, args) before each tool execution.
    Calls on_tool_result(name, result) after.
    on_notice receives retry/compact notices (shown dim, not sent to the model).
    Returns the final assistant text.
    """
    import time as _time

    if not model:
        model = get_model(cfg)
    anthropic_mode = cfg is not None and cfg.api_mode == "anthropic_messages"
    compacted_once = False
    while True:
        # Keep context within budget (drop oldest turns if very long)
        trimmed = _trim_messages(messages)
        if trimmed is not messages:
            messages[:] = trimmed
        # Repair tool-call chains broken by trimming / legacy saves (else 400)
        repaired = repair_tool_sequence(messages)
        if len(repaired) != len(messages):
            messages[:] = repaired
            if on_notice:
                on_notice("历史中有断裂的工具调用已清理")

        # Step 1: ask the model, streaming (transient errors retried with backoff)
        assistant_msg = None
        last_err: Exception | None = None
        for attempt in range(4):
            try:
                assistant_msg = _call_once_stream(
                    client, messages, tool_schemas, model, cfg,
                    on_text=on_text,
                    on_thought=on_thought,
                )
                break
            except Exception as e:
                last_err = e
                if _is_context_overflow(e) and not compacted_once:
                    try:
                        from .sessions import compact_messages
                        messages[:] = compact_messages(messages)
                        compacted_once = True
                        if on_notice:
                            on_notice("上下文超限，已压缩旧对话后重试")
                        continue
                    except Exception:
                        pass
                if _is_transient(e) and attempt < 3:
                    wait = 2 ** (attempt + 1)
                    if on_notice:
                        on_notice(f"请求抖动（{type(e).__name__}），{wait}s 后重试 {attempt + 1}/3")
                    _time.sleep(wait)
                    continue
                raise
        assert assistant_msg is not None, f"unreachable (last_err={last_err})"

        # Step 2: did it request tools?
        # NOTE: keep tool_calls IN the message — stripping them breaks the
        # next request with 400 "tool must respond to preceding tool_calls".
        tool_calls = assistant_msg.get("tool_calls")
        text = assistant_msg.get("content") or ""

        if tool_calls:
            messages.append(assistant_msg)

            for tc in tool_calls:
                name = tc["function"]["name"]
                raw_args = tc["function"]["arguments"]
                try:
                    args_dict = json.loads(raw_args) if raw_args else {}
                except json.JSONDecodeError:
                    args_dict = {"_raw": raw_args}
                if on_tool_call:
                    on_tool_call(name, args_dict)

                result = tools.execute(name, raw_args, skills=skills)

                # Cap long tool results so huge outputs don't blow the context
                result = _cap_result(result)

                if on_tool_result:
                    on_tool_result(name, result)
                if anthropic_mode:
                    # anthropic expects tool results as user-role content blocks
                    messages.append({
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": tc["id"],
                                "content": result,
                            }
                        ],
                    })
                else:
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": result,
                        }
                    )
            # loop again: model sees tool results, may emit more tool calls or final answer
            continue

        # No tool calls -> this is the final answer (already streamed via on_text).
        messages.append(assistant_msg)
        return text


def stream_final_text(
    client: OpenAI,
    messages: list[dict],
    tool_schemas: list[dict],
) -> Iterator[str]:
    """After a tool loop has settled, optionally stream the final answer in chunks.
    Not currently used by TUI but exposed for callers that want pure streaming.
    """
    # Strip the last assistant message; we'll re-ask for streaming version.
    if messages and messages[-1].get("role") == "assistant":
        messages = messages[:-1]
    for delta in stream_chat(client, messages, tools=tool_schemas or None):
        yield delta