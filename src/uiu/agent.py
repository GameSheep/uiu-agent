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


# ---------- public API ----------

def run_turn(
    client: OpenAI,
    messages: list[dict],
    tool_schemas: list[dict],
    skills: list | None = None,
    model: str = "",
    cfg: ModelConfig | None = None,
    on_text: Callable[[str], None] | None = None,
    on_tool_call: Callable[[str, dict], None] | None = None,
    on_tool_result: Callable[[str, str], None] | None = None,
) -> str:
    """Run a single user turn (may involve multiple LLM round-trips for tool use).

    Streams text deltas via on_text. Calls on_tool_call(name, args) before each
    tool execution. Calls on_tool_result(name, result) after.
    Returns the final assistant text.
    """
    if not model:
        model = get_model(cfg)
    anthropic_mode = cfg is not None and cfg.api_mode == "anthropic_messages"
    while True:
        # Step 1: ask the model
        assistant_msg = _call_once(client, messages, tool_schemas, model, cfg)

        # Step 2: did it request tools?
        tool_calls = assistant_msg.pop("tool_calls", None)
        text = assistant_msg.get("content") or ""

        if tool_calls:
            # No text to stream when tool calls present (typical); show what we have.
            if text and on_text:
                on_text(text)
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

        # No tool calls -> this is the final answer. Stream it for nice UX.
        messages.append(assistant_msg)
        if on_text and text:
            # When streaming isn't used in tool-loop mode, emit the whole text at once.
            on_text(text)
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