"""Cron — 定时任务：存 jobs.json，tick 到点跑 agent，结果落盘。

对齐 Hermes cron 的核心语义，砍到最小可用：
- schedule 支持：`30m/2h/1d/45s` 间隔、`daily HH:MM`、`M H * * *`（5 段 cron，只认分+时）、`once <ISO时间>` 单次
- `uiu cron add/list/remove/enable/disable/run/tick`；`uiu serve` 每 60s 自动 tick
- 每次运行输出写 `cron/output/<id>/<ts>.md`，防重跑锁 `.tick.lock`
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path


def cron_dir(workspace: Path) -> Path:
    d = Path(workspace) / "cron"
    d.mkdir(parents=True, exist_ok=True)
    (d / "output").mkdir(exist_ok=True)
    return d


def jobs_path(workspace: Path) -> Path:
    return cron_dir(workspace) / "jobs.json"


def load_jobs(workspace: Path) -> list[dict]:
    p = jobs_path(workspace)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_jobs(workspace: Path, jobs: list[dict]) -> None:
    jobs_path(workspace).write_text(json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------- schedule parsing ----------

_INTERVAL_RE = re.compile(r"^(\d+)\s*([smhd])$", re.I)
_DAILY_RE = re.compile(r"^daily\s+(\d{1,2}):(\d{2})$", re.I)
_CRON_RE = re.compile(r"^(\d{1,2})\s+(\d{1,2})\s+\*\s+\*\s+\*$")
_ONCE_RE = re.compile(r"^once\s+(.+)$", re.I)


def parse_schedule(spec: str) -> dict:
    """Parse a schedule spec into {kind, ...}. Raises ValueError on bad input."""
    s = (spec or "").strip()
    m = _INTERVAL_RE.match(s)
    if m:
        mult = {"s": 1, "m": 60, "h": 3600, "d": 86400}[m.group(2).lower()]
        return {"kind": "interval", "seconds": int(m.group(1)) * mult}
    m = _DAILY_RE.match(s)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        if h > 23 or mi > 59:
            raise ValueError("daily 时间非法（HH:MM，24h）")
        return {"kind": "daily", "hour": h, "minute": mi}
    m = _CRON_RE.match(s)
    if m:
        mi, h = int(m.group(1)), int(m.group(2))
        if h > 23 or mi > 59:
            raise ValueError("cron 分/时非法")
        return {"kind": "daily", "hour": h, "minute": mi}
    m = _ONCE_RE.match(s)
    if m:
        try:
            ts = datetime.fromisoformat(m.group(1).strip()).timestamp()
        except ValueError:
            raise ValueError("once 时间须为 ISO 格式，如 once 2026-09-05T10:00:00")
        return {"kind": "once", "at": ts}
    raise ValueError("schedule 支持：30m/2h/1d/45s、daily 09:00、'M H * * *'、once <ISO时间>")


def next_run_after(parsed: dict, after_ts: float | None = None) -> float:
    after = after_ts or time.time()
    kind = parsed["kind"]
    if kind == "interval":
        return after + parsed["seconds"]
    if kind == "once":
        return parsed["at"]
    # daily
    dt = datetime.fromtimestamp(after).replace(hour=parsed["hour"], minute=parsed["minute"], second=0, microsecond=0)
    if dt.timestamp() <= after:
        dt += timedelta(days=1)
    return dt.timestamp()


# ---------- job ops ----------

def add_job(workspace: Path, name: str, schedule: str, task: str) -> dict:
    parsed = parse_schedule(schedule)  # 先校验，非法直接抛
    jobs = load_jobs(workspace)
    jid = f"job-{int(time.time())}-{len(jobs) + 1}"
    now = time.time()
    job = {
        "id": jid, "name": name, "schedule": schedule,
        "task": task, "enabled": True,
        "created": now, "last_run": 0, "next_run": next_run_after(parsed, now),
    }
    jobs.append(job)
    save_jobs(workspace, jobs)
    return job


def remove_job(workspace: Path, job_id: str) -> bool:
    jobs = load_jobs(workspace)
    kept = [j for j in jobs if j["id"] != job_id and j["name"] != job_id]
    if len(kept) == len(jobs):
        return False
    save_jobs(workspace, kept)
    return True


def set_enabled(workspace: Path, job_id: str, enabled: bool) -> bool:
    jobs = load_jobs(workspace)
    hit = False
    for j in jobs:
        if j["id"] == job_id or j["name"] == job_id:
            j["enabled"] = enabled
            hit = True
    if hit:
        save_jobs(workspace, jobs)
    return hit


def due_jobs(workspace: Path, now: float | None = None) -> list[dict]:
    now = now or time.time()
    return [j for j in load_jobs(workspace) if j.get("enabled") and j.get("next_run", 0) <= now]


# ---------- running ----------

def _lock_path(workspace: Path) -> Path:
    return cron_dir(workspace) / ".tick.lock"


def _acquire_lock(workspace: Path, ttl: int = 300) -> bool:
    """防重跑锁（pid + 时间戳，TTL 过期可抢）。"""
    p = _lock_path(workspace)
    now = time.time()
    if p.exists():
        try:
            pid, ts = p.read_text(encoding="utf-8").split(":")
            if now - float(ts) < ttl:
                return False
        except Exception:
            pass
    try:
        p.write_text(f"{os.getpid()}:{now}", encoding="utf-8")
        return True
    except OSError:
        return False


def _release_lock(workspace: Path) -> None:
    try:
        _lock_path(workspace).unlink(missing_ok=True)
    except OSError:
        pass


def run_job(workspace: Path, job: dict, timeout: int = 180) -> str:
    """Run one job with a fresh agent loop. Returns output markdown path."""
    from .config import load_config
    from .llm import make_client
    from .workspace import load_workspace
    from .agent import run_turn
    from .gateway import _build_tool_schemas

    ws_path = Path(workspace)
    cfg = load_config(ws_path)
    ws = load_workspace(ws_path)
    client = make_client(cfg.model)
    messages = [
        {"role": "system", "content": ws.system_prompt()},
        {"role": "user", "content": f"[cron:{job.get('name')}] {job.get('task')}"},
    ]
    try:
        reply = run_turn(
            client=client, messages=messages,
            tool_schemas=_build_tool_schemas(ws), skills=ws.skills,
            model=cfg.model.default, cfg=cfg.model,
        )
    except Exception as e:
        reply = f"[cron error] {type(e).__name__}: {e}"
    ts = time.strftime("%Y%m%d_%H%M%S")
    out_dir = cron_dir(ws_path) / "output" / job["id"]
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{ts}.md"
    out_path.write_text(f"# {job.get('name')} @ {ts}\n\n{reply}\n", encoding="utf-8")
    return str(out_path)


def _reschedule(job: dict, now: float) -> None:
    try:
        parsed = parse_schedule(job["schedule"])
    except ValueError:
        job["enabled"] = False  # 非法 schedule：停用保平安
        return
    if parsed["kind"] == "once":
        job["enabled"] = False  # 单次跑完即停
        job["next_run"] = 0
    else:
        job["next_run"] = next_run_after(parsed, now)


def tick(workspace: Path) -> list[str]:
    """Run all due jobs once. Returns output paths. Lock-protected."""
    ws_path = Path(workspace)
    if not _acquire_lock(ws_path):
        return []
    ran: list[str] = []
    try:
        now = time.time()
        jobs = load_jobs(ws_path)
        if not jobs:
            return []
        for job in jobs:
            if not job.get("enabled") or job.get("next_run", 0) > now:
                continue
            try:
                out = run_job(ws_path, job)
                ran.append(out)
            except Exception as e:
                err_dir = cron_dir(ws_path) / "output" / job["id"]
                err_dir.mkdir(parents=True, exist_ok=True)
                (err_dir / f"{time.strftime('%Y%m%d_%H%M%S')}.err.md").write_text(
                    f"[tick error] {type(e).__name__}: {e}\n", encoding="utf-8")
            job["last_run"] = now
            _reschedule(job, now)
        save_jobs(ws_path, jobs)
        return ran
    finally:
        _release_lock(ws_path)
