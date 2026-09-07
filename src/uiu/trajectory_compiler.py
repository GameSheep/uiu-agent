"""Trajectory-to-Macro Auto-Compiler — Self-Coding Evolution Pattern.

Translates verified multi-step GUI and system action sequences into native,
zero-latency, type-annotated Python macro functions that execute in < 1 second.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


@dataclass
class ActionTrajectory:
    name: str
    description: str = ""
    target_app: str = ""
    steps: list[dict[str, Any]] = field(default_factory=list)
    parameters: list[str] = field(default_factory=list)  # dynamic variable names
    verification: dict[str, Any] = field(default_factory=dict)


# In-memory registry of dynamically compiled macro callables
COMPILED_MACROS: dict[str, Callable[..., str]] = {}


def _clean_identifier(name: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_]", "_", name.strip()).strip("_")
    if not safe or safe[0].isdigit():
        safe = "macro_" + safe
    return safe.lower()


def compile_trajectory_to_python(trajectory: ActionTrajectory) -> str:
    """Generate clean, native, standalone Python code from an ActionTrajectory."""
    fn_name = _clean_identifier(trajectory.name)
    params_str = ", ".join(trajectory.parameters) if trajectory.parameters else ""
    doc = trajectory.description.strip() or f"Auto-compiled macro for {trajectory.name}"

    lines = [
        '"""Auto-generated zero-latency macro compiled by uiu Trajectory Compiler."""',
        "from __future__ import annotations",
        "",
        "import time",
        "import json",
        "",
        f"def {fn_name}({params_str}) -> str:",
        f'    """{doc}"""',
        "    from uiu.window_manager import ensure_default_desktop, find_window, focus_window",
        "    from uiu.gui_primitives import mouse_click, paste_text, press_key, press_hotkey",
        "    from uiu.smart_interact import smart_interact",
        "    import win32gui",
        "    import win32con",
        "",
        "    ensure_default_desktop()",
        "    t_start = time.perf_counter()",
        "    logs = []",
        "",
    ]

    # Target window handling
    if trajectory.target_app:
        app_repr = repr(trajectory.target_app)
        lines.extend([
            f"    # Focus & restore {trajectory.target_app}",
            f"    win = find_window({app_repr})",
            "    active_rect = None",
            "    if win:",
            '        hwnd = win["hwnd"]',
            "        try:",
            "            if win32gui.IsIconic(hwnd):",
            "                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)",
            "            focus_window(hwnd)",
            "            time.sleep(0.12)",
            "            active_rect = win32gui.GetWindowRect(hwnd)",
            f'            logs.append("已置顶唤醒窗口: " + {app_repr})',
            "        except Exception as e:",
            '            logs.append("置顶异常: " + str(e))',
            "",
        ])

    # Action steps
    for i, step in enumerate(trajectory.steps, 1):
        action = step.get("action", "").lower().strip()
        lines.append(f"    # Step {i}: {action}")

        if action in ("click", "click_at"):
            x = step.get("x", 0)
            y = step.get("y", 0)
            lines.append(f"    mouse_click({x}, {y}, duration=0.0)")
            lines.append(f'    logs.append("点击坐标 ({x}, {y})")')

        elif action in ("smart_click", "smart_interact", "click_element"):
            tgt = step.get("target", "")
            # Check if target refers to a parameter
            tgt_repr = tgt if tgt in trajectory.parameters else repr(tgt)
            lines.append(f"    smart_res = smart_interact({tgt_repr}, region=active_rect, verify_change=False)")
            lines.append(f'    logs.append("智能交互: " + str(smart_res.get("tier_used")))')

        elif action in ("type", "type_text", "paste"):
            val = step.get("text", "")
            clear = bool(step.get("clear_before", True))
            val_repr = val if val in trajectory.parameters else repr(val)
            lines.append(f"    paste_text({val_repr}, clear_before={clear})")
            lines.append(f'    logs.append("注入文本: " + str({val_repr})[:30])')

        elif action == "hotkey":
            keys = step.get("keys", [])
            lines.append(f"    press_hotkey({repr(keys)})")
            lines.append(f'    logs.append("快捷键: {keys}")')

        elif action == "key":
            k = step.get("key", "enter")
            lines.append(f"    press_key({repr(k)})")
            lines.append(f'    logs.append("按键: {k}")')

        elif action == "wait":
            ms = float(step.get("ms", 100))
            lines.append(f"    time.sleep({ms / 1000.0})")

        lines.append("")

    # Result assembly
    lines.extend([
        "    elapsed_ms = (time.perf_counter() - t_start) * 1000.0",
        "    report = [",
        f'        "### [{trajectory.name}] 原生宏执行成功 (总耗时: " + f"{{elapsed_ms:.1f}}ms / {{elapsed_ms/1000.0:.2f}}s)",',
        '        "**步骤日志:**",',
        "    ]",
        '    for l in logs:',
        '        report.append("  * " + l)',
        '    return "\\n".join(report)',
        "",
    ])

    return "\n".join(lines)


def save_and_register_macro(
    trajectory: ActionTrajectory,
    save_dir: Path | None = None,
) -> tuple[str, Path]:
    """Compile trajectory into a Python file, save to workspace/macros/, and register dynamically."""
    code = compile_trajectory_to_python(trajectory)
    fn_name = _clean_identifier(trajectory.name)

    if save_dir is None:
        from .workspace import Workspace
        from .learning import _ws
        ws = _ws()
        root = ws.root if ws else Path.cwd()
        save_dir = root / "macros"

    save_dir.mkdir(parents=True, exist_ok=True)
    target_file = save_dir / f"{fn_name}.py"
    target_file.write_text(code, encoding="utf-8")

    # Dynamic in-memory import and registration
    spec = importlib.util.spec_from_file_location(fn_name, target_file)
    if spec and spec.loader:
        module = importlib.util.module_from_spec(spec)
        sys.modules[fn_name] = module
        spec.loader.exec_module(module)
        compiled_fn = getattr(module, fn_name, None)
        if callable(compiled_fn):
            COMPILED_MACROS[fn_name] = compiled_fn

    return fn_name, target_file


def run_compiled_macro(name: str, **kwargs) -> str:
    """Execute a compiled Python macro by name with sub-second zero-thinking latency."""
    clean_name = _clean_identifier(name)
    fn = COMPILED_MACROS.get(clean_name)
    if not fn:
        # Try loading from file
        from .workspace import Workspace
        from .learning import _ws
        ws = _ws()
        root = ws.root if ws else Path.cwd()
        target_file = root / "macros" / f"{clean_name}.py"
        if target_file.exists():
            spec = importlib.util.spec_from_file_location(clean_name, target_file)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                sys.modules[clean_name] = module
                spec.loader.exec_module(module)
                fn = getattr(module, clean_name, None)
                if callable(fn):
                    COMPILED_MACROS[clean_name] = fn

    if not fn:
        return f"[error] 未找到已编译的宏: {name} (注册表与本地文件均无)"

    try:
        return fn(**kwargs)
    except Exception as e:
        return f"[error] 宏 '{name}' 执行异常: {type(e).__name__}: {e}"
