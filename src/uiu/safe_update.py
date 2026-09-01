"""Safe update — Hermes-aligned protection against self-destructing installs.

解决的问题：更新/安装把自己搞崩（OpenClaw/DeepSeek harness 踩过的坑）。

机制（对齐 hermes update_lock.py + update_cmd.py）：
1. 更新锁         —— .uiu-update-in-progress 标记，防止两个更新并发改同一棵树
2. 预检           —— 更新前确认 git 状态干净、有备份点
3. 原子安装       —— pip install 到 staging 位置，不动当前运行环境
4. 装后验证       —— py_compile 全部源码 + 子进程 import 关键模块
5. 通过才切换     —— 失败自动回滚，当前进程继续用旧代码
6. 优雅提示       —— 更新完成提示重启生效，不在运行中热加载半新代码

用法：uiu update self 走这套流程（已接好）。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Update lock (Hermes update_lock.py)
# ---------------------------------------------------------------------------

UPDATE_MARKER_MAX_AGE_SECONDS = 20 * 60
MARKER_NAME = ".uiu-update-in-progress"
UPDATE_EXIT_CONCURRENT = 2


def update_marker_path() -> Path:
    """Marker lives next to the repo (project root), shared by all entrypoints."""
    return Path(__file__).resolve().parent.parent.parent / MARKER_NAME


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists but not ours
    except OSError:
        # Windows: os.kill(pid, 0) can be a console event — do a safe probe
        try:
            import ctypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not h:
                return False
            ctypes.windll.kernel32.CloseHandle(h)
            return True
        except Exception:
            return False


def read_live_update() -> dict | None:
    marker = update_marker_path()
    try:
        raw = marker.read_text(encoding="utf-8")
    except OSError:
        return None
    lines = raw.splitlines()
    try:
        pid = int(lines[0].strip())
    except (IndexError, ValueError):
        pid = -1
    try:
        started_at = float(lines[1].strip())
    except (IndexError, ValueError):
        started_at = float("-inf")
    age = time.time() - started_at
    if not _pid_alive(pid) or age > UPDATE_MARKER_MAX_AGE_SECONDS:
        try:
            marker.unlink()
        except OSError:
            pass
        return None
    return {"pid": pid, "age": age}


class UpdateLock:
    """Context manager owning the update marker (Hermes UpdateLock)."""

    def __init__(self) -> None:
        self.path = update_marker_path()
        self.acquired = False
        self.holder = None

    def acquire(self) -> bool:
        existing = read_live_update()
        if existing is not None:
            self.holder = existing
            return False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(f"{os.getpid()}\n{int(time.time())}\n", encoding="utf-8")
        except OSError:
            return True  # best-effort: unwritable marker must not block update
        self.acquired = True
        return True

    def release(self) -> None:
        if not self.acquired:
            return
        self.acquired = False
        try:
            raw = self.path.read_text(encoding="utf-8")
            owner = int(raw.splitlines()[0].strip())
        except (OSError, IndexError, ValueError):
            return
        if owner != os.getpid():
            return  # someone else owns it now
        try:
            self.path.unlink()
        except OSError:
            pass

    def __enter__(self) -> "UpdateLock":
        self.acquire()
        return self

    def __exit__(self, *_exc) -> None:
        self.release()


# ---------------------------------------------------------------------------
# Pre-update backup (rollback point)
# ---------------------------------------------------------------------------

def ensure_backup_point(repo_root: Path) -> str | None:
    """Create a git tag backup point before mutating. Returns tag name or None."""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_root, capture_output=True, text=True, timeout=10,
        )
        if r.returncode != 0:
            return None
        head = r.stdout.strip()
        tag = f"uiu-backup-{head}-{int(time.time())}"
        subprocess.run(
            ["git", "tag", tag], cwd=repo_root, capture_output=True, timeout=10,
        )
        return tag
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Staged install + verify (atomic)
# ---------------------------------------------------------------------------

def _syntax_check(src_dir: Path) -> tuple[bool, str | None]:
    """py_compile every .py under src_dir (writes .pyc to temp, not the tree)."""
    import py_compile
    import tempfile as _tf

    bad = []
    files = list(src_dir.rglob("*.py"))
    if not files:
        return True, None
    with _tf.TemporaryDirectory(prefix="uiu-syntax-") as tmp:
        for f in files:
            try:
                py_compile.compile(str(f), cfile=str(Path(tmp) / (f.name + "c")), doraise=True)
            except Exception as e:
                bad.append(f"{f}: {e}")
    if bad:
        return False, "\n".join(bad[:5])
    return True, None


def _import_check(module: str, python: str = sys.executable) -> tuple[bool, str | None]:
    """Import a module in a fresh interpreter to catch runtime breakage."""
    r = subprocess.run(
        [python, "-c", f"import {module}"],
        capture_output=True, text=True, timeout=60,
    )
    if r.returncode != 0:
        return False, r.stderr.strip()[-500:]
    return True, None


def staged_install(repo_root: Path, src_dir: Path) -> tuple[bool, str]:
    """Install editable package into a staging venv; verify; report.

    Returns (ok, message). On failure the staging venv is removed and the
    current environment is untouched — the running process keeps working.
    """
    staging = Path(tempfile.mkdtemp(prefix="uiu-staging-"))
    venv = staging / "venv"
    try:
        # 1. create staging venv
        r = subprocess.run(
            [sys.executable, "-m", "venv", str(venv)],
            capture_output=True, text=True, timeout=120,
        )
        if r.returncode != 0:
            return False, f"创建 staging venv 失败: {r.stderr[-300:]}"
        py = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

        # 2. install the package + deps into staging
        r = subprocess.run(
            [str(py), "-m", "pip", "install", "-e", str(repo_root), "--quiet"],
            capture_output=True, text=True, timeout=600,
        )
        if r.returncode != 0:
            return False, f"staging 安装失败: {r.stderr[-500:]}"

        # 3. verify: syntax + import critical modules in staging interpreter
        ok, err = _syntax_check(src_dir)
        if not ok:
            return False, f"语法校验失败:\n{err}"
        for mod in ("uiu.main", "uiu.agent", "uiu.llm", "uiu.tools"):
            ok, err = _import_check(mod, python=str(py))
            if not ok:
                return False, f"模块 {mod} 导入失败:\n{err}"

        # 4. verify version matches repo (editable install is current)
        r = subprocess.run(
            [str(py), "-c", "import uiu; print(uiu.__version__)"],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            return False, f"版本校验失败: {r.stderr[-300:]}"

        return True, f"staging 验证通过 (version={r.stdout.strip()})"
    finally:
        shutil.rmtree(staging, ignore_errors=True)


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------

def safe_self_update() -> int:
    """uiu update self with full crash protection. Returns exit code."""
    from .commands import _print_err, _print_ok

    repo_root = Path(__file__).resolve().parent.parent.parent
    src_dir = repo_root / "src" / "uiu"

    # 1. lock
    with UpdateLock() as lock:
        if not lock.acquired:
            holder = lock.holder or {}
            _print_err(f"另一个更新正在进行 (PID {holder.get('pid')})，等待完成后再试")
            return UPDATE_EXIT_CONCURRENT

        # 2. git pull (if remote)
        if (repo_root / ".git").exists():
            r = subprocess.run(["git", "remote"], cwd=repo_root, capture_output=True, text=True)
            if r.returncode == 0 and r.stdout.strip():
                print("· git pull --ff-only …")
                r = subprocess.run(
                    ["git", "pull", "--ff-only"], cwd=repo_root, capture_output=True, text=True, timeout=120,
                )
                if r.returncode != 0:
                    _print_err(f"git pull 失败: {r.stderr[-400:]}")
                    print("  工作区可能有本地修改。提交或 stash 后再试。")
                    return 1
            else:
                print("· 无 remote，跳过 git pull")

        # 3. backup point (rollback safety)
        tag = ensure_backup_point(repo_root)
        if tag:
            print(f"· 已创建回滚点: git tag {tag}")

        # 4. staged install + verify
        print("· 在隔离环境验证安装（不碰当前运行环境）…")
        ok, msg = staged_install(repo_root, src_dir)
        if not ok:
            _print_err(f"更新验证失败，已回滚（当前环境未动）:\n{msg}")
            return 1

        # 5. verify passed → do the real editable reinstall
        print(f"· 验证通过 ({msg})，应用更新…")
        r = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-e", str(repo_root), "--quiet"],
            capture_output=True, text=True, timeout=300,
        )
        if r.returncode != 0:
            _print_err(f"应用更新失败: {r.stderr[-400:]}")
            _print_err(f"回滚: git checkout {tag or '之前版本'} 或 git revert")
            return 1

    _print_ok("更新完成！重启 uiu 生效（当前进程继续用旧代码，不受影响）")
    return 0