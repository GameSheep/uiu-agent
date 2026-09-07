"""Task Checkpointing & Write-Ahead-Log (WAL) Engine.

Inspired by Claude Code, Hermes, and transactional database durability.
Persists autonomous execution steps to disk (workspace/checkpoints/<task_id>.jsonl).
Enables:
1. Resuming interrupted long-running tasks after process restarts or crashes.
2. Step auditing and replay.
3. Transactional rollback of side-effects using registered undo handlers.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass
class CheckpointEntry:
    task_id: str
    goal: str
    step_index: int
    tool_name: str
    tool_args: dict[str, Any]
    status: str  # "started" | "completed" | "failed" | "rolled_back"
    timestamp: float
    observation: str = ""
    undo_action: dict[str, Any] | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


def _get_checkpoint_dir() -> Path:
    from .workspace import Workspace
    from .learning import _ws
    ws = _ws()
    root = ws.root if ws else Path.cwd()
    p = root / "checkpoints"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_checkpoint_file(task_id: str) -> Path:
    safe_id = "".join(c if c.isalnum() else "_" for c in task_id)
    return _get_checkpoint_dir() / f"{safe_id}.jsonl"


def append_checkpoint_entry(entry: CheckpointEntry) -> None:
    """Atomic append of a task step entry to WAL."""
    filepath = get_checkpoint_file(entry.task_id)
    with open(filepath, "a", encoding="utf-8") as f:
        f.write(entry.to_json() + "\n")


def load_task_checkpoints(task_id: str) -> list[CheckpointEntry]:
    """Read all chronological checkpoints for a given task ID."""
    filepath = get_checkpoint_file(task_id)
    if not filepath.exists():
        return []

    entries = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    data = json.loads(line)
                    entries.append(CheckpointEntry(**data))
                except Exception:
                    pass
    return entries


def record_step_start(
    task_id: str,
    goal: str,
    step_index: int,
    tool_name: str,
    tool_args: dict[str, Any],
) -> CheckpointEntry:
    """Log that a step has started execution."""
    entry = CheckpointEntry(
        task_id=task_id,
        goal=goal,
        step_index=step_index,
        tool_name=tool_name,
        tool_args=tool_args,
        status="started",
        timestamp=time.time(),
    )
    append_checkpoint_entry(entry)
    return entry


def record_step_finish(
    task_id: str,
    step_index: int,
    observation: str,
    status: str = "completed",
    undo_action: dict[str, Any] | None = None,
) -> CheckpointEntry:
    """Log that a step has finished execution."""
    entries = load_task_checkpoints(task_id)
    goal = entries[-1].goal if entries else "Unknown Goal"
    tool_name = entries[-1].tool_name if entries else ""
    tool_args = entries[-1].tool_args if entries else {}

    entry = CheckpointEntry(
        task_id=task_id,
        goal=goal,
        step_index=step_index,
        tool_name=tool_name,
        tool_args=tool_args,
        status=status,
        timestamp=time.time(),
        observation=observation[:500],
        undo_action=undo_action,
    )
    append_checkpoint_entry(entry)
    return entry


def list_incomplete_tasks() -> list[dict[str, Any]]:
    """Scan checkpoints directory for tasks that were started but never completed or reached terminal state."""
    chk_dir = _get_checkpoint_dir()
    incomplete = []

    for p in chk_dir.glob("*.jsonl"):
        task_id = p.stem
        entries = load_task_checkpoints(task_id)
        if not entries:
            continue

        last_entry = entries[-1]
        is_finished = last_entry.status in ("completed", "failed", "rolled_back") and (
            "任务已完成" in last_entry.observation or "all_done" in last_entry.tool_args
        )

        completed_steps = len([e for e in entries if e.status == "completed"])
        incomplete.append({
            "task_id": task_id,
            "goal": entries[0].goal,
            "completed_steps": completed_steps,
            "last_step": last_entry.step_index,
            "last_status": last_entry.status,
            "last_tool": last_entry.tool_name,
            "is_terminal": is_finished,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(last_entry.timestamp)),
        })

    return incomplete


def rollback_task(task_id: str) -> str:
    """Execute registered undo actions in reverse chronological order to rollback task side-effects."""
    from .desktop_tools import dispatch_tool

    entries = load_task_checkpoints(task_id)
    if not entries:
        return f"[error] 未找到任务 {task_id} 的检查点记录"

    rolled_back_count = 0
    errors = []

    # Reverse order
    for entry in reversed(entries):
        if entry.status == "completed" and entry.undo_action:
            fn = entry.undo_action.get("tool_name")
            args = entry.undo_action.get("tool_args", {})
            if fn:
                res = dispatch_tool(fn, args)
                if res.startswith("[error]"):
                    errors.append(f"步骤 {entry.step_index} ({fn}) 回滚失败: {res}")
                else:
                    rolled_back_count += 1

    # Record rollback entry
    append_checkpoint_entry(CheckpointEntry(
        task_id=task_id,
        goal=entries[0].goal,
        step_index=len(entries) + 1,
        tool_name="rollback_task",
        tool_args={"task_id": task_id},
        status="rolled_back",
        timestamp=time.time(),
        observation=f"成功回滚 {rolled_back_count} 个动作",
    ))

    if errors:
        return f"[warning] 任务回滚完成 (成功 {rolled_back_count} 个动作，{len(errors)} 个异常): {'; '.join(errors)}"
    return f"[ok] 任务 {task_id} 已成功回滚 {rolled_back_count} 个动作"
