"""Hierarchical Dual-Agent Architecture — Microsoft UFO Framework Pattern.

Decomposes complex multi-application desktop tasks into:
1. HostAgent (Global Orchestrator):
   - High-level intent parsing & multi-app task decomposition.
   - Cross-application data flow orchestration.
   - Monitors execution state across sub-goals.
2. AppAgent (Application-Specific Specialist):
   - Manages single application lifecycle (window focus, restore).
   - Mounts dedicated fast pipelines (CC Switch, WeChat, ChatGPT) or specialized skills.
   - Localized Observe-Act-Verify loops confined to the app's boundary.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AppSubTask:
    app_name: str
    goal: str
    inputs: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"  # pending, running, success, failed
    result: str = ""
    duration_ms: float = 0.0


class AppAgent:
    """Specialist agent focused on a single application's execution."""

    def __init__(self, app_name: str):
        self.app_name = app_name

    def execute(self, subtask: AppSubTask) -> AppSubTask:
        t0 = time.perf_counter()
        subtask.status = "running"
        app_lower = self.app_name.lower().strip()
        goal = subtask.goal

        from .window_manager import find_window, focus_window, ensure_default_desktop
        import win32gui
        import win32con

        ensure_default_desktop()

        # Step 1: Ensure window is focused & restored
        win = find_window(self.app_name)
        active_rect = None
        if win:
            hwnd = win["hwnd"]
            try:
                if win32gui.IsIconic(hwnd):
                    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                focus_window(hwnd)
                active_rect = win32gui.GetWindowRect(hwnd)
            except Exception:
                pass

        # Step 2: Route to specialized fast pipeline if recognized
        try:
            if "cc switch" in app_lower or "cc-switch" in app_lower:
                from .fast_pipeline import update_cc_switch_provider_remark
                # Extract provider and remark from goal / inputs
                provider = subtask.inputs.get("provider", "Zhipu GLM")
                remark = subtask.inputs.get("remark", "")
                if not remark:
                    # Regex match
                    m = re.search(r"备注[为改是成到\s]+([^\s,，。]+)", goal)
                    remark = m.group(1) if m else "已更新"
                m_p = re.search(r"([A-Za-z0-9_\-\s]+)的?备注", goal)
                if m_p and m_p.group(1).strip():
                    p_cand = m_p.group(1).strip()
                    if p_cand.lower() not in ("cc switch", "修改", "把"):
                        provider = p_cand

                res = update_cc_switch_provider_remark(provider_name=provider, new_remark=remark)
                subtask.status = "success"
                subtask.result = res

            elif "微信" in app_lower or "wechat" in app_lower:
                from .wechat_tools import send_wechat
                contact = subtask.inputs.get("contact", "")
                message = subtask.inputs.get("message", "")
                if not contact:
                    m_c = re.search(r"[给发向到]([^\s,，。]+)[发说送]", goal)
                    contact = m_c.group(1) if m_c else "文件传输助手"
                if not message:
                    m_m = re.search(r"[发说送][内容为是：:\s]*([^\n。]+)", goal)
                    message = m_m.group(1) if m_m else goal

                res = send_wechat(contact=contact, message=message)
                subtask.status = "success" if "[ok]" in res else "failed"
                subtask.result = res

            elif "chatgpt" in app_lower:
                from .fast_pipeline import check_chatgpt_quota
                res = check_chatgpt_quota()
                subtask.status = "success"
                subtask.result = res

            else:
                # Generic App execution via smart_interact
                from .smart_interact import smart_interact
                res = smart_interact(target=goal, action="click", region=active_rect)
                subtask.status = "success" if res.get("success") else "failed"
                subtask.result = json.dumps(res, ensure_ascii=False)

        except Exception as e:
            subtask.status = "failed"
            subtask.result = f"[error] AppAgent({self.app_name}) 异常: {type(e).__name__}: {e}"

        subtask.duration_ms = (time.perf_counter() - t0) * 1000.0
        return subtask


class HostAgent:
    """Global orchestrator: intent decomposition, app agent dispatching & result aggregation."""

    def __init__(self):
        pass

    def decompose_goal(self, goal: str) -> list[AppSubTask]:
        """Decompose compound goal into app-specific subtasks."""
        subtasks = []
        # Check compound delimiters: 然后, 再, 接着, 并
        delimiters = r"[;；\n]|(?:\s*然后\s*)|(?:\s*再\s*)|(?:\s*接着\s*)|(?:\s*并且\s*)"
        parts = [p.strip() for p in re.split(delimiters, goal) if p.strip()]

        known_apps = [
            ("CC Switch", ["cc switch", "cc-switch", "switch", "供应商"]),
            ("微信", ["微信", "wechat", "发消息给", "通知"]),
            ("ChatGPT", ["chatgpt", "gpt额度", "查额度"]),
            ("浏览器", ["打开网址", "搜索", "网页", "http"]),
        ]

        for part in parts:
            assigned_app = "通用桌面"
            for app_name, keywords in known_apps:
                if any(kw in part.lower() for kw in keywords):
                    assigned_app = app_name
                    break
            subtasks.append(AppSubTask(app_name=assigned_app, goal=part))

        if not subtasks:
            subtasks.append(AppSubTask(app_name="通用桌面", goal=goal))

        return subtasks

    def execute_goal(self, goal: str) -> dict[str, Any]:
        t_start = time.perf_counter()
        subtasks = self.decompose_goal(goal)
        executed_tasks = []

        overall_success = True
        for i, st in enumerate(subtasks, 1):
            agent = AppAgent(st.app_name)
            res_task = agent.execute(st)
            executed_tasks.append(res_task)
            if res_task.status != "success":
                overall_success = False

        total_ms = (time.perf_counter() - t_start) * 1000.0

        timeline = []
        for i, t in enumerate(executed_tasks, 1):
            timeline.append(f"第 {i} 阶段 [{t.app_name}]: {t.status.upper()} ({t.duration_ms:.1f}ms)\n  子任务: {t.goal}\n  输出: {t.result[:120]}")

        return {
            "success": overall_success,
            "goal": goal,
            "total_duration_ms": round(total_ms, 1),
            "subtasks_count": len(executed_tasks),
            "timeline": timeline,
            "tasks": [
                {
                    "app": t.app_name,
                    "goal": t.goal,
                    "status": t.status,
                    "duration_ms": round(t.duration_ms, 1),
                    "result": t.result,
                }
                for t in executed_tasks
            ],
        }


def hierarchical_execute(goal: str) -> str:
    """Execute compound goal via HostAgent & AppAgent hierarchical orchestration."""
    host = HostAgent()
    res = host.execute_goal(goal)
    report = [
        f"### [分级协同执行报告] {'全部成功' if res['success'] else '部分未完成'} (总耗时: {res['total_duration_ms']:.1f}ms)",
        f"**用户宏观总目标:** {res['goal']}",
        f"**拆解执行流水线 (共 {res['subtasks_count']} 阶段):**",
    ]
    for tl in res["timeline"]:
        report.append(f"- {tl}")
    return "\n".join(report)
