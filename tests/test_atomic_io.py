"""Durability + concurrency guarantees for uiu state files (audit P0-2).

These tests encode why the atomic/locked writers exist:

- a failed write must never destroy the previous content (crash / disk full)
- readers must never observe a half-written file
- concurrent read-modify-write must not lose updates (threads *and* processes)
- a corrupt state file is backed up, not silently dropped
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from uiu._atomic import (atomic_write_json, atomic_write_text, file_lock,
                         load_json_tolerant, locked_update_json)


def _tmp_leftovers(directory: Path) -> list[str]:
    return [p.name for p in directory.iterdir() if p.name.endswith(".tmp")]


# --------------------------------------------------------------------------
# atomicity
# --------------------------------------------------------------------------


def test_failed_replace_keeps_previous_content(tmp_path, monkeypatch):
    """写入过程中失败（磁盘满 / 被杀）不能毁掉旧文件。"""
    target = tmp_path / "state.json"
    atomic_write_json(target, {"version": 1})

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        atomic_write_json(target, {"version": 2})
    monkeypatch.undo()

    assert json.loads(target.read_text(encoding="utf-8")) == {"version": 1}
    assert _tmp_leftovers(tmp_path) == [], "失败后不能留下临时文件"


def test_temp_file_lives_next_to_target(tmp_path, monkeypatch):
    """临时文件必须与目标同目录（否则 os.replace 不是原子的）。"""
    seen: list[str] = []
    real_mkstemp = __import__("tempfile").mkstemp

    def spy(*args, **kwargs):
        seen.append(str(kwargs.get("dir", "")))
        return real_mkstemp(*args, **kwargs)

    monkeypatch.setattr("tempfile.mkstemp", spy)
    target = tmp_path / "deep" / "nested" / "state.json"
    atomic_write_json(target, {"a": 1})
    assert seen and Path(seen[0]) == target.parent
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1}


def test_atomic_write_creates_parents_and_is_utf8(tmp_path):
    target = tmp_path / "a" / "b" / "note.md"
    atomic_write_text(target, "中文内容 ✅")
    assert target.read_text(encoding="utf-8") == "中文内容 ✅"


# --------------------------------------------------------------------------
# corruption handling
# --------------------------------------------------------------------------


def test_corrupt_json_is_backed_up_not_dropped(tmp_path):
    target = tmp_path / "broken.json"
    target.write_text("{ this is not json", encoding="utf-8")

    assert load_json_tolerant(target, {"fallback": True}) == {"fallback": True}
    assert not target.exists(), "损坏文件应被移走（备份）"
    backups = list(tmp_path.glob("broken.json.corrupt-*"))
    assert backups, "必须留下备份以便人工恢复"
    assert "not json" in backups[0].read_text(encoding="utf-8")


def test_corrupt_session_is_self_healing(tmp_path):
    """损坏的会话文件不能拖垮 resume：备份 + 当作不存在。"""
    from uiu import sessions as S

    ws = tmp_path / "ws"
    S.save_session(ws, "good", [{"role": "user", "content": "hi"}])
    (S.sessions_dir(ws) / "bad.json").write_text("{truncated", encoding="utf-8")

    assert S.load_session(ws, "bad") is None
    listed = {s["id"] for s in S.list_sessions(ws)}
    assert "good" in listed
    assert "bad" not in listed
    assert list(S.sessions_dir(ws).glob("bad.json.corrupt-*"))


# --------------------------------------------------------------------------
# concurrency
# --------------------------------------------------------------------------


def test_locked_update_serialises_threads(tmp_path):
    target = tmp_path / "counter.json"

    def add(i: int):
        def _mutate(cur):
            data = cur if isinstance(cur, dict) else {}
            time.sleep(0.001)          # 放大竞态窗口
            data[f"k{i}"] = i
            return data
        return _mutate

    threads = [threading.Thread(target=locked_update_json,
                                args=(target, add(i)), kwargs={"default": {}})
               for i in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    data = json.loads(target.read_text(encoding="utf-8"))
    assert data == {f"k{i}": i for i in range(12)}, "并发读-改-写丢了更新"


def test_lock_timeout_raises(tmp_path):
    target = tmp_path / "locked.json"
    with file_lock(target, timeout=5):
        with pytest.raises(TimeoutError):
            with file_lock(target, timeout=0.2):
                pass


def test_locked_update_serialises_processes(tmp_path):
    """真正的跨进程互斥（TUI + gateway + daemon 三方共写）。"""
    target = tmp_path / "shared.json"
    script = tmp_path / "worker.py"
    script.write_text(
        "import sys\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, r'%s')\n"
        "from uiu._atomic import locked_update_json\n"
        "tag = sys.argv[2]\n"
        "def mutate(cur):\n"
        "    data = cur if isinstance(cur, dict) else {}\n"
        "    import time; time.sleep(0.05)\n"
        "    data[tag] = tag\n"
        "    return data\n"
        "locked_update_json(Path(sys.argv[1]), mutate, default={})\n"
        % str(Path(__file__).resolve().parent.parent / "src"),
        encoding="utf-8")

    procs = [subprocess.Popen([sys.executable, str(script), str(target), f"p{i}"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
             for i in range(4)]
    for p in procs:
        p.wait(timeout=60)

    data = json.loads(target.read_text(encoding="utf-8"))
    assert data == {f"p{i}": f"p{i}" for i in range(4)}, f"跨进程丢了更新: {data}"


def test_concurrent_cron_add_job_keeps_all(tmp_path):
    """真实 API 层验证：并发 add_job 不能互相覆盖，id 也必须唯一。"""
    from uiu import cron

    ws = tmp_path / "ws"
    errors: list[BaseException] = []

    def add(i: int):
        try:
            cron.add_job(ws, f"job{i}", "1d", f"echo {i}")
        except BaseException as exc:      # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=add, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors
    jobs = cron.load_jobs(ws)
    names = sorted(j["name"] for j in jobs)
    assert names == [f"job{i}" for i in range(6)], names
    ids = [j["id"] for j in jobs]
    assert len(ids) == len(set(ids)), f"job id 冲突: {ids}"


def test_session_save_survives_failed_write(tmp_path, monkeypatch):
    """真实路径：保存一半失败时，上一个版本仍能 resume。"""
    from uiu import sessions as S

    ws = tmp_path / "ws"
    S.save_session(ws, "s1", [{"role": "user", "content": "first"}])

    def boom(src, dst):
        raise OSError("killed mid-write")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        S.save_session(ws, "s1", [{"role": "user", "content": "second"}])
    monkeypatch.undo()

    restored = S.load_session(ws, "s1")
    assert restored == [{"role": "user", "content": "first"}]
    assert _tmp_leftovers(S.sessions_dir(ws)) == []
