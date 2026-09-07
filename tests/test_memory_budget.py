"""Bounded memory — MEMORY.md budget + usage meter in prompt/tool results."""

from pathlib import Path


def _ws_root(tmp_cwd) -> Path:
    p = tmp_cwd / "workspace"
    p.mkdir(parents=True, exist_ok=True)
    return p


def test_memory_usage_meter_reflects_fill(tmp_cwd):
    from uiu.learning import memory_usage
    root = _ws_root(tmp_cwd)
    (root / "MEMORY.md").write_text("# MEMORY\n", encoding="utf-8")
    assert "0%" in memory_usage()
    (root / "MEMORY.md").write_text("# MEMORY\n" + "- [2026-09-01] " + "x" * 3000 + "\n", encoding="utf-8")
    assert "100" in memory_usage()


def test_memory_add_rejects_over_budget(tmp_cwd):
    from uiu.learning import memory_add, memory_replace, MEMORY_BUDGET
    root = _ws_root(tmp_cwd)
    (root / "MEMORY.md").write_text("# MEMORY\n" + "- [2026-09-01] " + "y" * MEMORY_BUDGET + "\n", encoding="utf-8")
    out = memory_add("新记忆")
    assert out.startswith("[error]") and "记忆库已满" in out
    assert "新记忆" not in (root / "MEMORY.md").read_text(encoding="utf-8")


def test_memory_add_after_replace_frees_budget(tmp_cwd):
    from uiu.learning import memory_add, memory_replace, MEMORY_BUDGET
    root = _ws_root(tmp_cwd)
    big = "- [2026-09-01] " + "y" * MEMORY_BUDGET
    (root / "MEMORY.md").write_text("# MEMORY\n" + big + "\n")
    memory_replace(big, "- [2026-09-01] 精简后")
    out = memory_add("新记忆能写了")
    assert out.startswith("[ok]"), out
    assert "新记忆能写了" in (root / "MEMORY.md").read_text(encoding="utf-8")


def test_memory_recall_includes_meter(tmp_cwd):
    from uiu.learning import memory_add, memory_recall
    root = _ws_root(tmp_cwd)
    (root / "MEMORY.md").write_text("# MEMORY\n", encoding="utf-8")
    memory_add("偏好短回答")
    out = memory_recall()
    assert "偏好短回答" in out and "%" in out


def test_system_prompt_includes_meter(tmp_cwd):
    from uiu.workspace import Workspace
    root = _ws_root(tmp_cwd)
    (root / "MEMORY.md").write_text("# MEMORY\n- [2026-09-01] 记住的事\n", encoding="utf-8")
    ws = Workspace(root=root)
    ws.reload_memory()
    prompt = ws.system_prompt()
    assert "MEMORY (across sessions)" in prompt and "%" in prompt


def test_memory_budget_not_in_clean_system_prompt(tmp_cwd):
    """No MEMORY.md → no meter line, system prompt stays clean."""
    from uiu.workspace import Workspace
    root = _ws_root(tmp_cwd)
    ws = Workspace(root=root)
    assert "MEMORY" not in ws.system_prompt()
