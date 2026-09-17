"""Workspace 备份 / 恢复（审计 §3.4）。

备份是用户数据唯一的兜底：没有它，一次误删 / 一次迁移失败 / 一次磁盘故障就是永久损失。

- create_backup(workspace)：把关键文件打包成 <workspace>/backups/uiu-backup-<ts>.zip
- restore_backup(workspace, archive)：**恢复前先自动备份**（可撤销），并拒绝 zip-slip
- maybe_daily_backup(workspace)：daemon 起手调用，24h 内只做一次
- prune_backups(workspace, keep)：滚动保留最近 N 份
"""

from __future__ import annotations

import json
import shutil
import time
import zipfile
from pathlib import Path
from typing import Iterable

__all__ = [
    "DEFAULT_KEEP", "backup_dir", "list_backups", "create_backup",
    "restore_backup", "prune_backups", "maybe_daily_backup",
]

DEFAULT_KEEP = 7
BACKUP_DIRNAME = "backups"
_INCLUDE_FILES = ("config.yaml", ".env", "SOUL.md", "IDENTITY.md", "USER.md", "MEMORY.md")
_INCLUDE_DIRS = ("sessions", "cron", "skills")
# 这些子路径不进备份：日志、备份自己、cron 产物、锁文件、缓存
_SKIP_PARTS = {BACKUP_DIRNAME, "logs", "output", "__pycache__"}
_META_NAME = "BACKUP.json"


def backup_dir(workspace: Path | str) -> Path:
    return Path(workspace) / BACKUP_DIRNAME


def _skip(path: Path, workspace: Path) -> bool:
    rel = path.relative_to(workspace)
    if any(part in _SKIP_PARTS for part in rel.parts):
        return True
    return (path.suffix == ".lock" or path.name.endswith(".tmp")
            or ".corrupt-" in path.name)


def _iter_members(workspace: Path) -> Iterable[Path]:
    for name in _INCLUDE_FILES:
        p = workspace / name
        if p.is_file():
            yield p
    for name in _INCLUDE_DIRS:
        root = workspace / name
        if not root.is_dir():
            continue
        for p in sorted(root.rglob("*")):
            if p.is_file() and not _skip(p, workspace):
                yield p


def list_backups(workspace: Path | str) -> list[Path]:
    d = backup_dir(workspace)
    if not d.is_dir():
        return []
    return sorted(d.glob("uiu-backup-*.zip"),
                  key=lambda p: p.stat().st_mtime, reverse=True)


def create_backup(workspace: Path | str, *, to: Path | str | None = None,
                  keep: int | None = None, note: str = "") -> Path:
    """打包 workspace 关键文件，返回 zip 路径。"""
    from . import __version__

    ws = Path(workspace)
    target_dir = Path(to) if to else backup_dir(ws)
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = target_dir / f"uiu-backup-{stamp}.zip"
    n = 1
    while path.exists():
        path = target_dir / f"uiu-backup-{stamp}-{n}.zip"
        n += 1

    members = list(_iter_members(ws))
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for member in members:
            zf.write(member, member.relative_to(ws).as_posix())
        zf.writestr(_META_NAME, json.dumps({
            "uiu_version": __version__,
            "created": stamp,
            "note": note,
            "files": len(members),
        }, ensure_ascii=False, indent=2))
    if keep is not None and Path(to or backup_dir(ws)) == backup_dir(ws):
        prune_backups(ws, keep)
    return path


def prune_backups(workspace: Path | str, keep: int = DEFAULT_KEEP) -> list[Path]:
    """只保留最近 keep 份（keep<=0 表示不裁剪）。只动 workspace 自己的备份目录。"""
    if keep is None or keep <= 0:
        return []
    removed: list[Path] = []
    for old in list_backups(workspace)[keep:]:
        try:
            old.unlink()
            removed.append(old)
        except OSError:
            pass
    return removed


def _safe_members(zf: zipfile.ZipFile) -> list[str]:
    """拒绝绝对路径与上跳路径（zip-slip），元数据文件不还原。"""
    out: list[str] = []
    for info in zf.infolist():
        if info.is_dir():
            continue
        name = info.filename.replace(chr(92), "/")
        if name == _META_NAME:
            continue
        pure = Path(name)
        if pure.is_absolute() or ".." in pure.parts or name.startswith("/") or ":" in name:
            raise ValueError(f"备份包含越界路径，已拒绝恢复: {name}")
        out.append(name)
    return out


def restore_backup(workspace: Path | str, archive: Path | str, *,
                   keep: int = DEFAULT_KEEP) -> dict:
    """把备份解回 workspace；恢复前先做一次安全备份（可撤销）。"""
    ws = Path(workspace)
    archive = Path(archive)
    if not archive.is_file():
        raise FileNotFoundError(f"备份文件不存在: {archive}")

    safety = None
    if any((ws / name).exists() for name in _INCLUDE_FILES) or (ws / "sessions").is_dir():
        safety = create_backup(ws, note="pre-restore", keep=None)

    restored: list[str] = []
    with zipfile.ZipFile(archive) as zf:
        members = _safe_members(zf)          # 越界就整体拒绝，不写任何文件
        for name in members:
            dest = ws / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(name) as src, open(dest, "wb") as dst:
                shutil.copyfileobj(src, dst)
            restored.append(name)
    prune_backups(ws, keep)
    return {"restored": restored, "safety_backup": str(safety) if safety else ""}


def maybe_daily_backup(workspace: Path | str, *, keep: int = DEFAULT_KEEP,
                       interval_hours: float = 24.0) -> Path | None:
    """距上次备份超过 interval_hours 才做（daemon/gateway 起手调用）。"""
    existing = list_backups(workspace)
    if existing and (time.time() - existing[0].stat().st_mtime) < interval_hours * 3600:
        return None
    return create_backup(workspace, keep=keep, note="auto-daily")
