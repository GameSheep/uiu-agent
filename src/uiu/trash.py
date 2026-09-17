"""回收站：破坏性操作先移进来，可恢复（审计 §4.1）。

之前删会话/删宏/删渠道/删定时任务都是**直接消失**，没有撤销。这里给一个最小回收站：

- 文件类（会话、宏）：整个文件移入 <workspace>/.trash/<entry>，meta 里记住原相对路径；
- 记录类（渠道配置、定时任务）：把配置 dict 存成 payload.json，恢复时再插回配置/任务表；
- restore 拒绝覆盖已存在的目标；purge 按天数清理；daemon 每天顺手清一次。

所有写操作走 _atomic 的锁，避免与 TUI/gateway 并发打架。
"""

from __future__ import annotations

import json
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from ._atomic import atomic_write_json, file_lock

__all__ = ["DEFAULT_KEEP_DAYS", "trash_dir", "add_file", "add_record",
           "get_entry", "list_entries", "restore", "purge", "describe"]

DEFAULT_KEEP_DAYS = 7
_META = "meta.json"
_PAYLOAD = "payload.json"


def trash_dir(workspace: Path | str) -> Path:
    return Path(workspace) / ".trash"


def _safe(text: str, limit: int = 24) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff.-]+", "-", str(text)).strip("-")[:limit] or "item"


def _new_entry_id(kind: str, label: str) -> str:
    return f"{time.strftime('%Y%m%d-%H%M%S')}-{kind}-{_safe(label)}-{uuid.uuid4().hex[:4]}"


def describe(entry: dict) -> str:
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(entry.get("created", 0)))
    return (f"{entry.get('id')}  [{entry.get('kind')}]  {entry.get('label') or '-'}  "
            f"{when}  原位置: {entry.get('origin') or entry.get('kind')}")


def _write_meta(root: Path, meta: dict) -> None:
    atomic_write_json(root / _META, meta, indent=2)


def add_file(workspace: Path | str, path: Path | str, *, kind: str = "file",
             label: str = "") -> dict:
    """把文件/目录移入回收站，返回 meta。"""
    ws = Path(workspace)
    src = Path(path)
    if not src.exists():
        raise FileNotFoundError(f"要删除的对象不存在: {src}")
    entry_id = _new_entry_id(kind, label or src.stem)
    root = trash_dir(ws) / entry_id
    root.mkdir(parents=True, exist_ok=True)
    try:
        origin = str(src.relative_to(ws)).replace("\\", "/")
    except ValueError:
        origin = str(src)
    with file_lock(trash_dir(ws) / ".trash"):
        moved = root / src.name
        shutil.move(str(src), str(moved))
    meta = {"id": entry_id, "type": "file", "kind": kind, "label": label or src.stem,
            "origin": origin, "name": src.name,
            "created": time.time(), "size": _size_of(moved)}
    _write_meta(root, meta)
    return meta


def add_record(workspace: Path | str, kind: str, payload: Any, *, label: str = "") -> dict:
    """把一份配置（渠道/定时任务…）存进回收站，返回 meta。"""
    ws = Path(workspace)
    entry_id = _new_entry_id(kind, label)
    root = trash_dir(ws) / entry_id
    root.mkdir(parents=True, exist_ok=True)
    atomic_write_json(root / _PAYLOAD, payload, indent=2)
    meta = {"id": entry_id, "type": "record", "kind": kind, "label": label,
            "created": time.time()}
    _write_meta(root, meta)
    return meta


def _size_of(path: Path) -> int:
    try:
        if path.is_file():
            return path.stat().st_size
        return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
    except OSError:
        return 0


def get_entry(workspace: Path | str, entry_id: str) -> dict | None:
    root = trash_dir(workspace) / str(entry_id)
    meta_file = root / _META
    if not meta_file.is_file():
        return None
    try:
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
    except Exception:
        return None
    meta["_root"] = str(root)
    return meta


def list_entries(workspace: Path | str) -> list[dict]:
    d = trash_dir(workspace)
    if not d.is_dir():
        return []
    out = []
    for root in d.iterdir():
        if not root.is_dir():
            continue
        meta = get_entry(workspace, root.name)
        if meta:
            out.append(meta)
    return sorted(out, key=lambda m: m.get("created", 0), reverse=True)


def restore(workspace: Path | str, entry_id: str) -> tuple[bool, str]:
    """把回收站条目还原。返回 (是否成功, 说明)。"""
    ws = Path(workspace)
    meta = get_entry(ws, entry_id)
    if meta is None:
        return False, f"回收站里没有 {entry_id}"

    if meta.get("type") == "file":
        root = Path(meta["_root"])
        moved = root / str(meta.get("name", ""))
        if not moved.exists():
            return False, f"条目内容已丢失: {moved}"
        dest = ws / str(meta.get("origin", ""))
        if dest.exists():
            return False, f"原位置已有同名文件，先处理它: {dest}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(moved), str(dest))
        _drop(meta["_root"])
        return True, f"已恢复 {meta.get('label')} → {dest}"

    kind = meta.get("kind")
    payload = json.loads((Path(meta["_root"]) / _PAYLOAD).read_text(encoding="utf-8"))
    if kind == "channel":
        from .config import load_config, save_config
        from .config import ChannelConfig
        cfg = load_config(ws)
        if any(c.name == payload.get("name") for c in cfg.channels):
            return False, f"渠道 {payload.get('name')} 已存在"
        cfg.channels.append(ChannelConfig(**payload))
        save_config(ws, cfg)
    elif kind == "cron_job":
        from . import cron
        cron.update_jobs(ws, lambda jobs: jobs + [payload])
    else:
        return False, f"不知道如何恢复 kind={kind}"
    _drop(meta["_root"])
    return True, f"已恢复 {kind} {meta.get('label') or ''}".strip()


def _drop(root: str) -> None:
    shutil.rmtree(root, ignore_errors=True)


def purge(workspace: Path | str, *, days: float = DEFAULT_KEEP_DAYS) -> list[str]:
    """清理超过 days 天的条目，返回被清理的 id。"""
    if days is None or days <= 0:
        return []
    cutoff = time.time() - days * 86400
    removed = []
    for meta in list_entries(workspace):
        if meta.get("created", 0) < cutoff:
            _drop(meta["_root"])
            removed.append(meta["id"])
    return removed
