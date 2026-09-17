"""Atomic state-file writes + advisory cross-process locks.

Why this module exists (audit P0-2 / §3.1-3.2):

- Every state file used to be written with a plain `write_text`. A crash, a full
  disk or a killed process mid-write leaves a **truncated** sessions/config/cron/
  MEMORY.md file — i.e. user data loss that cannot be recovered.
- The TUI, `uiu serve` and `uiu daemon` all write the same workspace files. With
  no locking, two "read-modify-write" cycles lose updates.

Primitives:
- `atomic_write_text` / `atomic_write_json` / `atomic_write_bytes`:
  write to a temp file in the same directory, flush + fsync, then `os.replace`
  (atomic on the same filesystem). A failure leaves the old file untouched.
- `file_lock`: advisory lock over a `.lock` sidecar, `msvcrt.locking` on Windows
  and `fcntl.flock` elsewhere, with a timeout.
- `locked_update_json`: read → mutate → atomic write, all under the lock.
- `load_json_tolerant`: a corrupt file is renamed to `<name>.corrupt-<ts>` and the
  default is returned, instead of raising (or silently dropping data).
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

__all__ = [
    "atomic_write_bytes",
    "atomic_write_text",
    "atomic_write_json",
    "file_lock",
    "locked_update_json",
    "load_json_tolerant",
    "backup_corrupt",
]


# --------------------------------------------------------------------------
# atomic writes
# --------------------------------------------------------------------------


def atomic_write_bytes(path: Path | str, data: bytes, *, fsync: bool = True) -> None:
    """Write *data* to *path* atomically (temp file + os.replace)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp",
                                    dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            if fsync:
                try:
                    os.fsync(fh.fileno())
                except OSError:
                    pass          # some filesystems refuse fsync; the replace still helps
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def atomic_write_text(path: Path | str, text: str, *, encoding: str = "utf-8") -> None:
    atomic_write_bytes(path, text.encode(encoding))


def atomic_write_json(path: Path | str, obj: Any, *, indent: int | None = None,
                      ensure_ascii: bool = False) -> None:
    payload = json.dumps(obj, ensure_ascii=ensure_ascii, indent=indent)
    atomic_write_text(path, payload)


# --------------------------------------------------------------------------
# corruption handling
# --------------------------------------------------------------------------


def backup_corrupt(path: Path | str) -> Path | None:
    """Move a corrupt file aside so the next write starts clean. Returns the backup."""
    path = Path(path)
    if not path.exists():
        return None
    target = path.with_name(f"{path.name}.corrupt-{int(time.time())}")
    n = 1
    while target.exists():
        target = path.with_name(f"{path.name}.corrupt-{int(time.time())}-{n}")
        n += 1
    try:
        os.replace(path, target)
    except OSError:
        return None
    try:                    # 数据被移到一边是重要事件，必须留下痕迹
        from .log import get_logger
        get_logger("atomic").warning("损坏文件已备份: %s → %s", path.name, target.name)
    except Exception:
        pass
    return target


def load_json_tolerant(path: Path | str, default: Any = None) -> Any:
    """Parse JSON, or back the file up and return *default* when it is corrupt."""
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        backup_corrupt(path)
        return default


# --------------------------------------------------------------------------
# locking
# --------------------------------------------------------------------------

try:                                    # Windows
    import msvcrt

    def _lock_fd(fd: int) -> bool:
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False

    def _unlock_fd(fd: int) -> None:
        try:
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass

except ImportError:                     # POSIX
    import fcntl

    def _lock_fd(fd: int) -> bool:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False

    def _unlock_fd(fd: int) -> None:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass


_PROCESS_LOCKS: dict[str, threading.RLock] = {}
_PROCESS_LOCKS_GUARD = threading.Lock()


def _process_lock(path: Path) -> threading.RLock:
    key = os.path.normcase(str(path))
    with _PROCESS_LOCKS_GUARD:
        lock = _PROCESS_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _PROCESS_LOCKS[key] = lock
        return lock


@contextmanager
def file_lock(path: Path | str, timeout: float = 10.0, poll: float = 0.05) -> Iterator[None]:
    """Exclusive lock for *path*, valid across threads **and** processes.

    Two layers, because neither alone is enough:
    - a per-path `threading.RLock` (Windows byte-range locks do *not* conflict
      between handles of the same process, so threads need their own gate)
    - an OS-level lock over the `<path>.lock` sidecar (`msvcrt.locking` /
      `fcntl.flock`) which is what actually excludes other processes
    """
    lock_path = Path(f"{path}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    process_lock = _process_lock(lock_path)
    if not process_lock.acquire(timeout=max(0.0, timeout) if timeout else -1):
        raise TimeoutError(f"获取文件锁超时（{timeout}s）: {lock_path}")

    fd = -1
    acquired = False
    try:
        fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o666)
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            if _lock_fd(fd):
                acquired = True
                break
            if time.monotonic() >= deadline:
                raise TimeoutError(f"获取文件锁超时（{timeout}s，被其他进程占用）: {lock_path}")
            time.sleep(poll)
        yield
    finally:
        if acquired:
            _unlock_fd(fd)
        if fd >= 0:
            os.close(fd)
        process_lock.release()


def locked_update_json(path: Path | str, mutator: Callable[[Any], Any], *,
                       default: Any = None, timeout: float = 10.0,
                       indent: int | None = None) -> Any:
    """Read-modify-write *path* under the lock so concurrent writers don't lose data."""
    path = Path(path)
    with file_lock(path, timeout=timeout):
        current = load_json_tolerant(path, default)
        updated = mutator(current)
        atomic_write_json(path, updated, indent=indent)
        return updated
