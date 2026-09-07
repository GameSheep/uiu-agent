"""Dynamic Context Compaction & Rolling State Summarization.

Inspired by Claude Code, Cursor, and Open Interpreter.
Solves context overflow in long-running autonomous sessions by:
1. Compacting verbose tool outputs (large OCR dumps, file dumps) into dense operational summaries.
2. Generating structured rolling checkpoints ("Completed Actions & Discovered State").
3. Preserving root user intent + rolling state checkpoint + recent detailed turns.
4. Guaranteeing 100% schema integrity for OpenAI and Anthropic tool_call_id pairs.
"""

from __future__ import annotations

import json
import re
from typing import Any


def compress_tool_output(tool_name: str, raw_output: str, max_chars: int = 350) -> str:
    """Compress a verbose tool execution result into a dense summary line if it exceeds budget."""
    if not raw_output or len(raw_output) <= max_chars:
        return raw_output

    # 1. OCR or Set-of-Mark catalogs
    if "Set-of-Mark" in raw_output or "OCR" in raw_output or "tag" in tool_name.lower() or "ocr" in tool_name.lower():
        lines = [line.strip() for line in raw_output.splitlines() if line.strip()]
        total_items = sum(1 for line in lines if line.startswith("|") and not line.startswith("| :"))
        sample = "; ".join(lines[2:6]) if len(lines) > 2 else raw_output[:100]
        return f"[compacted] {tool_name} 结果共 {total_items} 项元素 (节选: {sample[:150]}...)"

    # 2. Window list
    if "window_list" in tool_name or "可见窗口" in raw_output:
        return f"[compacted] 窗口列表探测完成 (共包含多应用视口，前导: {raw_output[:120]}...)"

    # 3. File listings or long text
    first_line = raw_output.splitlines()[0] if raw_output.splitlines() else raw_output[:60]
    tail = raw_output[-120:].replace("\n", " ")
    return f"[compacted] {first_line} ... [中间 {len(raw_output) - 240} 字符已压缩] ... {tail}"



def extract_trajectory_digest(messages: list[dict[str, Any]]) -> str:
    """Extract chronological actions taken, tools invoked, and key discoveries."""
    digest_items = []

    for m in messages:
        role = m.get("role")
        content = str(m.get("content") or "")
        tool_calls = m.get("tool_calls") or []

        if role == "assistant" and tool_calls:
            for tc in tool_calls:
                fn = tc.get("function", {})
                fn_name = fn.get("name", "tool")
                try:
                    args = json.loads(fn.get("arguments", "{}"))
                    args_summary = ", ".join(f"{k}={v}" for k, v in list(args.items())[:2])
                except Exception:
                    args_summary = ""
                digest_items.append(f"- 动作: 调用 `{fn_name}({args_summary})`")

        elif role == "tool":
            # Extract key status from tool result
            first_line = content.splitlines()[0] if content else ""
            if "[ok]" in first_line:
                digest_items.append(f"  -> 结果: {first_line[:90]}")
            elif "[error]" in first_line or "[blocked]" in first_line:
                digest_items.append(f"  -> 异常: {first_line[:90]}")

    if not digest_items:
        return "尚无执行动作。"

    return "\n".join(digest_items[-15:])


def compact_conversation_history(
    messages: list[dict[str, Any]],
    max_chars: int = 35_000,
    keep_recent_turns: int = 4,
) -> list[dict[str, Any]]:
    """Compact long conversations within token budget while preserving critical task context.

    Structure maintained:
    [System Message]
    [Root User Request]
    [Context Checkpoint / Rolled Summary of Past Actions]
    [Recent N detailed turns (User / Assistant / Tool results)]
    """
    if not messages:
        return []

    # Calculate total length
    total_len = sum(len(str(m.get("content") or "")) + 300 for m in messages)
    if total_len <= max_chars:
        return messages

    system_msgs = [m for m in messages if m.get("role") == "system"]
    non_system = [m for m in messages if m.get("role") != "system"]

    if len(non_system) <= keep_recent_turns * 2:
        # Not enough turns to compact; return original
        return messages

    # Split into historic turns and recent turns
    # We want to ensure we don't break assistant tool_calls / tool response pairs
    split_idx = max(1, len(non_system) - (keep_recent_turns * 2))

    # Adjust split_idx to never cut between an assistant tool_call and its tool results
    while split_idx < len(non_system) and non_system[split_idx].get("role") == "tool":
        split_idx += 1

    root_user_msg = non_system[0] if non_system[0].get("role") == "user" else None
    historic_slice = non_system[1:split_idx] if root_user_msg else non_system[:split_idx]
    recent_slice = non_system[split_idx:]

    # Synthesize rolling state summary from historic turns
    digest = extract_trajectory_digest(historic_slice)
    checkpoint_content = (
        f"### [系统自适应上下文状态压缩包 / Rolling State Checkpoint]\n"
        f"为确保超长多轮执行不超限，前序 {len(historic_slice)} 轮中间调用细节已压缩，核心提炼如下：\n\n"
        f"**已完成的操作轨迹与状态总结**：\n"
        f"{digest}\n\n"
        f"> 提示：请直接基于上述已完成状态继续推进后续工作，无需重复已成功执行的操作。"
    )

    checkpoint_msg = {
        "role": "user",
        "content": checkpoint_content,
    }

    compacted: list[dict[str, Any]] = []
    compacted.extend(system_msgs)
    if root_user_msg:
        compacted.append(root_user_msg)
    compacted.append(checkpoint_msg)
    compacted.extend(recent_slice)

    return compacted
