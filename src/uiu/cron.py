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

from ._atomic import (atomic_write_json, atomic_write_text, file_lock,
                      load_json_tolerant, locked_update_json)
from .log import get_logger
from .schema import migrate, stamp


def cron_dir(workspace: Path) -> Path:
    d = Path(workspace) / "cron"
    d.mkdir(parents=True, exist_ok=True)
    (d / "output").mkdir(exist_ok=True)
    return d


def jobs_path(workspace: Path) -> Path:
    return cron_dir(workspace) / "jobs.json"


def _jobs_of(payload) -> list[dict]:
    """兼容 v0（顶层裸 list）与 v1（{schema, jobs}）。"""
    data, _ = migrate("jobs", payload)
    if isinstance(data, list):                 # 迁移路径缺失时的兜底
        return data
    jobs = data.get("jobs") if isinstance(data, dict) else None
    return jobs if isinstance(jobs, list) else []


def load_jobs(workspace: Path) -> list[dict]:
    return _jobs_of(load_json_tolerant(jobs_path(workspace), []))


def save_jobs(workspace: Path, jobs: list[dict]) -> None:
    atomic_write_json(jobs_path(workspace), stamp("jobs", {"jobs": jobs}), indent=2)


def update_jobs(workspace: Path, mutate) -> list[dict]:
    """锁内「读-升级-改-写」：迁移必须在锁内做，否则会把 v1 数据当空表覆盖。"""
    result: dict = {}

    def _inner(payload):
        jobs = _jobs_of(payload)
        result["jobs"] = mutate(jobs)
        return stamp("jobs", {"jobs": result["jobs"]})

    locked_update_json(jobs_path(workspace), _inner, default=[], indent=2)
    return result.get("jobs", [])


# ---------- schedule parsing ----------

_INTERVAL_RE = re.compile(r"^(\d+)\s*([smhd])$", re.I)
_DAILY_RE = re.compile(r"^daily\s+(\d{1,2}):(\d{2})$", re.I)
_CRON_RE = re.compile(r"^(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)$")
_ONCE_RE = re.compile(r"^once\s+(.+)$", re.I)


def _parse_cron_field(field: str, lo: int, hi: int, name: str) -> list[int]:
    """Parse one cron field: int, range (a-b), step (*/n or a-b/n), list (a,b).
    Returns the set of matching values in [lo, hi]."""
    values: set[int] = set()
    field = (field or "").strip()
    if field == "":
        raise ValueError(f"cron {name} 字段为空")
    for part in field.split(","):
        part = part.strip()
        if not part:
            continue
        step = 1
        if "/" in part:
            part, _, step_s = part.partition("/")
            try:
                step = int(step_s)
            except ValueError:
                raise ValueError(f"cron {name} 步长非法: {step_s}")
            if step < 1:
                raise ValueError(f"cron {name} 步长须为正整数")
        if part == "*":
            lo_v, hi_v = lo, hi
        elif "-" in part and not part.startswith("-"):
            a, _, b = part.partition("-")
            try:
                lo_v, hi_v = int(a), int(b)
            except ValueError:
                raise ValueError(f"cron {name} 范围非法: {part}")
        else:
            try:
                v = int(part)
            except ValueError:
                raise ValueError(f"cron {name} 字段非法: {part}")
            if not (lo <= v <= hi):
                raise ValueError(f"cron {name} 超出范围 {lo}-{hi}: {v}")
            lo_v = hi_v = v
        if lo_v < lo or hi_v > hi or lo_v > hi_v:
            raise ValueError(f"cron {name} 超出范围 {lo}-{hi}: {part}")
        for v in range(lo_v, hi_v + 1, step):
            values.add(v)
    if not values:
        raise ValueError(f"cron {name} 无有效值")
    return sorted(values)


def _cron_spec_to_parsed(fields: list[str]) -> dict:
    """Five-field cron → parsed dict. All-star dom/mon/dow folds to 'daily'."""
    minute, hour, dom, mon, dow = fields
    minutes = _parse_cron_field(minute, 0, 59, "分")
    hours = _parse_cron_field(hour, 0, 23, "时")
    doms = _parse_cron_field(dom, 1, 31, "日")
    mons = _parse_cron_field(mon, 1, 12, "月")
    dows = _parse_cron_field(dow, 0, 7, "周")
    # cron 规范：7 等价于 0（周日）
    dows = sorted({0 if d == 7 else d for d in dows})
    # 兼容旧语义：全 * 的 5 段 cron 等价于 daily
    if dom == "*" and mon == "*" and dow == "*":
        if len(minutes) == 1 and len(hours) == 1:
            return {"kind": "daily", "hour": hours[0], "minute": minutes[0]}
    return {"kind": "cron", "minutes": minutes, "hours": hours,
            "doms": doms, "mons": mons, "dows": dows}


def parse_schedule(spec: str) -> dict:
    """Parse a schedule spec into {kind, ...}. Raises ValueError on bad input.

    Supports: `30m/2h/1d/45s`, `daily HH:MM`, full 5-field cron
    (`M H dom mon dow` with `*/n`, ranges and lists), `once <ISO>`.
    """
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
        return _cron_spec_to_parsed(list(m.groups()))
    m = _ONCE_RE.match(s)
    if m:
        try:
            ts = datetime.fromisoformat(m.group(1).strip()).timestamp()
        except ValueError:
            raise ValueError("once 时间须为 ISO 格式，如 once 2026-09-05T10:00:00")
        return {"kind": "once", "at": ts}
    raise ValueError("schedule 支持：30m/2h/1d/45s、daily 09:00、'M H dom mon dow'（支持 */n/范围/列表）、once <ISO时间>")


def _cron_dow_matches(parsed_dows: list[int], py_weekday: int) -> bool:
    """Match a Python weekday (0=Mon..6=Sun) against normalized cron dow values.

    cron dow: 0/7=Sun, 1=Mon, 2=Tue, 3=Wed, 4=Thu, 5=Fri, 6=Sat.
    So python weekday w ↔ cron dow (w + 1) % 7.
    """
    cron_dow = (py_weekday + 1) % 7
    return cron_dow in parsed_dows


def _cron_next_match(parsed: dict, after_ts: float) -> float:
    """Earliest datetime after after_ts matching the 5-field cron rule."""
    dt = datetime.fromtimestamp(after_ts).replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(60 * 24 * 366):  # 最多扫一年，防死循环
        if dt.month in parsed["mons"] and dt.day in parsed["doms"] \
                and _cron_dow_matches(parsed["dows"], dt.weekday()) \
                and dt.hour in parsed["hours"] and dt.minute in parsed["minutes"]:
            return dt.timestamp()
        dt += timedelta(minutes=1)
    raise ValueError("cron 在一年内无匹配时间（检查字段）")


def next_run_after(parsed: dict, after_ts: float | None = None) -> float:
    after = after_ts or time.time()
    kind = parsed["kind"]
    if kind == "interval":
        return after + parsed["seconds"]
    if kind == "once":
        return parsed["at"]
    if kind == "cron":
        return _cron_next_match(parsed, after)
    # daily
    dt = datetime.fromtimestamp(after).replace(hour=parsed["hour"], minute=parsed["minute"], second=0, microsecond=0)
    if dt.timestamp() <= after:
        dt += timedelta(days=1)
    return dt.timestamp()


# ---------- job ops ----------

def add_job(workspace: Path, name: str, schedule: str, task: str, run_shell: bool = False) -> dict:
    parsed = parse_schedule(schedule)  # 先校验，非法直接抛
    now = time.time()
    job = {
        "id": "", "name": name, "schedule": schedule,
        "task": task, "enabled": True,
        "run_shell": bool(run_shell),  # Hermes no_agent：脚本任务零 token，不跑 agent
        "created": now, "last_run": 0, "next_run": next_run_after(parsed, now),
    }

    def _mutate(jobs: list[dict]) -> list[dict]:
        # id 在锁内生成，避免两个进程算出同一个 job-N
        job["id"] = f"job-{int(now)}-{len(jobs) + 1}"
        return jobs + [job]

    update_jobs(workspace, _mutate)
    return job


def remove_job(workspace: Path, job_id: str) -> bool:
    removed = {"hit": False}

    def _mutate(jobs: list[dict]) -> list[dict]:
        kept = [j for j in jobs if j["id"] != job_id and j["name"] != job_id]
        removed["hit"] = len(kept) != len(jobs)
        return kept

    update_jobs(workspace, _mutate)
    return bool(removed["hit"])


def set_enabled(workspace: Path, job_id: str, enabled: bool) -> bool:
    changed = {"hit": False}

    def _mutate(jobs: list[dict]) -> list[dict]:
        for j in jobs:
            if j["id"] == job_id or j["name"] == job_id:
                j["enabled"] = enabled
                changed["hit"] = True
        return jobs

    update_jobs(workspace, _mutate)
    return bool(changed["hit"])


def due_jobs(workspace: Path, now: float | None = None) -> list[dict]:
    now = now or time.time()
    return [j for j in load_jobs(workspace) if j.get("enabled") and j.get("next_run", 0) <= now]


# ---------- running ----------

def _tick_lock_path(workspace: Path) -> Path:
    """Tick 互斥用的锁文件（真正的 OS 级锁，不再是 pid+TTL 抢写）。"""
    return cron_dir(workspace) / ".tick"


def _run_shell_job(job: dict) -> str:
    """Hermes no_agent 脚本任务：跑命令拿 stdout，零 LLM 零 token。"""
    import subprocess
    from ._sandbox import check_command, truncate_output
    cmd = job.get("task", "").strip()
    ok, msg = check_command(cmd)
    if not ok:
        return msg
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=300, stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return "[error] 命令超时（>300s）"
    except Exception as e:
        return f"[error] {type(e).__name__}: {e}"
    out = result.stdout or ""
    if result.stderr:
        out += "\n[stderr]\n" + result.stderr
    if result.returncode != 0:
        out += f"\n[exit code: {result.returncode}]"
    return truncate_output(out.strip() or "(no output)")


def run_job(workspace: Path, job: dict, timeout: int = 180) -> str:
    """Run one job with a fresh agent loop (or shell if run_shell). Returns output markdown path."""
    from .desktop_guard import execution_guard, ExecutionContext

    ws_path = Path(workspace)
    with execution_guard(ExecutionContext.CRON_SCHEDULED_RUN, source=f"cron:{job.get('id', job.get('name', 'job'))}"):
        if job.get("run_shell"):
            reply = _run_shell_job(job)
        else:
            from .config import load_config
            from .llm import make_client
            from .workspace import load_workspace
            from .agent import run_turn
            from .gateway import _build_tool_schemas

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
        atomic_write_text(out_path, f"# {job.get('name')} @ {ts}\n\n{reply}\n")
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
    try:
        # 进程级 + 跨进程互斥；拿不到说明另一个进程正在 tick，直接跳过
        with file_lock(_tick_lock_path(ws_path), timeout=0.2):
            return _tick_locked(ws_path)
    except TimeoutError:
        return []


def _tick_locked(ws_path: Path) -> list[str]:
    log = get_logger("cron")
    ran: list[str] = []
    now = time.time()
    jobs = load_jobs(ws_path)
    if not jobs:
        return []
    for job in jobs:
        if not job.get("enabled") or job.get("next_run", 0) > now:
            continue
        log.info("running job %s (%s)", job.get("name"), job.get("id"))
        try:
            out = run_job(ws_path, job)
            ran.append(out)
            log.info("job %s done → %s", job.get("name"), out)
        except Exception as e:
            log.exception("job %s failed: %s", job.get("name"), e)
            err_dir = cron_dir(ws_path) / "output" / job["id"]
            err_dir.mkdir(parents=True, exist_ok=True)
            atomic_write_text(err_dir / f"{time.strftime('%Y%m%d_%H%M%S')}.err.md",
                              f"[tick error] {type(e).__name__}: {e}\n")
        job["last_run"] = now
        _reschedule(job, now)
    save_jobs(ws_path, jobs)
    return ran


# ---------- agent-facing cron tools ----------

def _default_ws_path() -> Path:
    from .commands import _workspace
    class DummyArgs:
        workspace = None
    return _workspace(DummyArgs())


def cron_add_job(name: str, schedule: str, task: str) -> str:
    """Add a scheduled cron job (supports absolute ISO time like 'once 2026-09-07T18:30:00', interval '30m', 'daily 09:00', etc.)."""
    ws = _default_ws_path()
    try:
        job = add_job(ws, name=name, schedule=schedule, task=task)
        dt = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(job["next_run"]))
        return f"[ok] 已成功创建定时任务 '{job['name']}' (ID: {job['id']})，调度规则: {job['schedule']}，下次运行时间: {dt}"
    except Exception as e:
        return f"[error] 创建定时任务失败: {type(e).__name__}: {e}"


def cron_list_jobs() -> str:
    """List all scheduled jobs in the workspace."""
    ws = _default_ws_path()
    jobs = load_jobs(ws)
    if not jobs:
        return "当前没有配置任何定时任务。"
    lines = [f"### 定时任务列表 (共 {len(jobs)} 个):", ""]
    for j in jobs:
        st = "启用" if j.get("enabled", True) else "已停用"
        nr = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(j.get("next_run", 0))) if j.get("next_run") else "-"
        lines.append(f"- **{j.get('name')}** (ID: `{j.get('id')}`) [{st}]")
        lines.append(f"  - 调度: `{j.get('schedule')}` | 下次运行: {nr}")
        lines.append(f"  - 任务: {j.get('task')}")
    return "\n".join(lines)


def cron_remove_job(job_id: str) -> str:
    """Remove a scheduled job by its id or name."""
    ws = _default_ws_path()
    jobs = load_jobs(ws)
    target = None
    for j in jobs:
        if j.get("id") == job_id or j.get("name") == job_id:
            target = j
            break
    if not target:
        return f"[error] 未找到 ID 或名称为 '{job_id}' 的定时任务"
    remove_job(ws, target["id"])
    return f"[ok] 已成功删除定时任务 '{target.get('name')}' ({target['id']})"


CRON_ADD_JOB_DEF = {
    "type": "function",
    "function": {
        "name": "cron_add_job",
        "description": "创建绝对定时或周期定时任务（支持绝对时间如 'once 2026-09-07T18:00:00'、每天固定时间 'daily 09:00'、间隔时间 '30m'/'2h'、5段cron表达式）。到点自动执行指定任务。",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "定时任务名称"},
                "schedule": {"type": "string", "description": "调度时间规则，如 'once 2026-09-07T18:00:00'、'daily 09:30'、'30m'、'0 9 * * 1-5'"},
                "task": {"type": "string", "description": "到点需要执行的任务提示词/指令（例如'运行 send_email_via_gui 给 boss@company.com 发送今日报告'）"},
            },
            "required": ["name", "schedule", "task"],
        },
    },
}

CRON_LIST_JOBS_DEF = {
    "type": "function",
    "function": {
        "name": "cron_list_jobs",
        "description": "列出当前工作区中所有配置的定时任务列表与下次触发时间。",
        "parameters": {"type": "object", "properties": {}},
    },
}

CRON_REMOVE_JOB_DEF = {
    "type": "function",
    "function": {
        "name": "cron_remove_job",
        "description": "删除指定的定时任务（支持传入任务 ID 或任务名称）。",
        "parameters": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "定时任务 ID 或名称"},
            },
            "required": ["job_id"],
        },
    },
}

CRON_TOOLS: dict[str, dict] = {
    "cron_add_job": {"def": CRON_ADD_JOB_DEF, "fn": cron_add_job},
    "cron_list_jobs": {"def": CRON_LIST_JOBS_DEF, "fn": cron_list_jobs},
    "cron_remove_job": {"def": CRON_REMOVE_JOB_DEF, "fn": cron_remove_job},
}


def cron_tool_defs() -> list[dict]:
    return [t["def"] for t in CRON_TOOLS.values()]

