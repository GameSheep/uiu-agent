"""Memory unification tests — learning + RAG write the SAME MEMORY.md format,
and hot-reload hooks refresh a running workspace after a write."""

import os
from pathlib import Path


def _ws_root(tmp_cwd) -> Path:
    p = tmp_cwd / "workspace"
    p.mkdir(parents=True, exist_ok=True)
    return p


def test_memory_add_appends_line_format(tmp_cwd):
    from uiu.learning import memory_add
    root = _ws_root(tmp_cwd)
    (root / "MEMORY.md").write_text("# MEMORY\n", encoding="utf-8")
    out = memory_add("用户喜欢用 Python")
    assert out.startswith("[ok]"), out
    text = (root / "MEMORY.md").read_text(encoding="utf-8")
    assert "- [20" in text and "用户喜欢用 Python" in text
    assert "###" not in text, "add_memory must not use the old block format"


def test_rag_add_memory_same_file_same_format(tmp_cwd):
    """memory_rag.add_memory must append to learning's MEMORY.md with the same format."""
    from uiu.learning import memory_add
    from uiu.memory_rag import add_memory
    root = _ws_root(tmp_cwd)
    memory_add("先写一条")
    out = add_memory("用户工作在 Windows")
    assert out.startswith("[ok]"), out
    text = (root / "MEMORY.md").read_text(encoding="utf-8")
    assert "先写一条" in text and "用户工作在 Windows" in text
    assert "###" not in text
    # only one file, same path resolution
    assert list(root.glob("MEMORY.md")) and "用户工作在 Windows" in text


def test_memory_remove_registered_and_works(tmp_cwd):
    from uiu.tools import BUILTIN_TOOLS, call_tool
    import json
    root = _ws_root(tmp_cwd)
    assert "memory_remove" in BUILTIN_TOOLS
    call_tool("memory_add", json.dumps({"content": "待删除的临时记忆"}))
    assert "待删除的临时记忆" in (root / "MEMORY.md").read_text(encoding="utf-8")
    out = call_tool("memory_remove", json.dumps({"content": "待删除的临时记忆"}))
    assert out.startswith("[ok]"), out
    assert "待删除的临时记忆" not in (root / "MEMORY.md").read_text(encoding="utf-8")


def test_memory_hot_reload_updates_workspace(tmp_cwd):
    """A registered workspace reload hook refreshes ws.memory after memory_add."""
    from uiu.workspace import Workspace
    from uiu.learning import memory_add, register_memory_hook
    ws_root = tmp_cwd / "workspace"
    ws_root.mkdir(parents=True, exist_ok=True)
    ws = Workspace(root=ws_root)
    (ws_root / "MEMORY.md").write_text("# MEMORY\n- [2026-01-01] old\n", encoding="utf-8")
    ws.reload_memory()
    assert "old" in ws.memory
    register_memory_hook(ws.reload_memory)
    memory_add("热刷新可见的新记忆")
    assert "热刷新可见的新记忆" in ws.memory, "ws.memory should refresh without reload()"


def test_skill_create_no_empty_exec(tmp_cwd):
    from uiu.learning import skill_create
    root = _ws_root(tmp_cwd)
    out = skill_create("my_skill", "测试技能", "do thing")
    assert out.startswith("[ok]"), out
    text = (root / "skills" / "my_skill" / "SKILL.md").read_text(encoding="utf-8")
    assert "exec:" not in text, "skill_create must not write an empty exec: line"


def test_slash_memory_triggers_hot_reload(tmp_cwd):
    """/memory writes to MEMORY.md and refreshes a registered ws (no restart)."""
    from uiu.workspace import Workspace, load_workspace
    from uiu.learning import register_memory_hook
    from uiu.slash import dispatch, SlashContext
    from uiu.config import load_config
    root = _ws_root(tmp_cwd)
    cfg = load_config(tmp_cwd)
    ws = Workspace(root=root)
    register_memory_hook(ws.reload_memory)
    said: list[str] = []
    ctx = SlashContext(ws=load_workspace(root), cfg=cfg, client=None, messages=[],
                       say=said.append)
    handled, _ = dispatch("/memory 通过斜杠记一条", ctx)
    assert handled
    assert "通过斜杠记一条" in ws.memory, "ws.memory should refresh after /memory"
