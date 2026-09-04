"""Workspace loading tolerates broken skill files."""

from pathlib import Path


def _ws(tmp_path: Path, skills: dict[str, str]) -> Path:
    ws = tmp_path / "ws"
    (ws / "skills").mkdir(parents=True)
    (ws / "SOUL.md").write_text("# SOUL\ntest\n", encoding="utf-8")
    for name, body in skills.items():
        d = ws / "skills" / name
        d.mkdir()
        (d / "SKILL.md").write_text(body, encoding="utf-8")
    return ws


def test_broken_skill_file_skipped_not_fatal(tmp_path):
    from uiu.workspace import load_workspace
    ws = _ws(tmp_path, {"good": "---\nname: good\ndescription: ok\n---\n\nexec: echo\n"})
    # unreadable dir entry: a file where a skill dir is expected is ignored
    (ws / "skills" / "notadir.md").write_text("x", encoding="utf-8")
    loaded = load_workspace(ws)
    assert any(s.name == "good" for s in loaded.skills)


def test_system_prompt_assembles(tmp_path):
    from uiu.workspace import load_workspace
    ws = _ws(tmp_path, {})
    loaded = load_workspace(ws)
    assert "SOUL" in loaded.system_prompt()
