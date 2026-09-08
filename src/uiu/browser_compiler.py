"""Browser Trajectory-to-Macro Auto-Compiler — Self-Evolving Playwright Engine.

Translates verified exploratory browser interaction sequences into standalone,
ultra-fast, self-healing Python Playwright macro functions:
1. Preserves user browser session: Attaches directly to running Chrome over CDP.
2. Parameterized inputs: Form values and search queries can be dynamically passed as kwargs.
3. Self-healing baked in: All element clicks and inputs run through `resilient_browser_action`.
4. Hot-patching: Passes `macro_file_path=__file__` so visual recoveries patch the script on disk.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable

from .browser_explorer import BrowserTrajectory


COMPILED_BROWSER_MACROS: dict[str, Callable[..., str]] = {}


def _clean_macro_identifier(name: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_]", "_", name.strip()).strip("_")
    if not safe or safe[0].isdigit():
        safe = "web_macro_" + safe
    return safe.lower()


def compile_browser_trajectory_to_python(trajectory: BrowserTrajectory) -> str:
    """Generate clean, standalone Python code from a BrowserTrajectory."""
    fn_name = _clean_macro_identifier(trajectory.name)
    params_str = ", ".join(trajectory.parameters) if trajectory.parameters else ""
    doc = trajectory.description.strip() or f"Auto-compiled browser macro for {trajectory.name}"

    lines = [
        '"""Auto-generated zero-latency Playwright browser macro compiled by uiu."""',
        "from __future__ import annotations",
        "",
        "import json",
        "import time",
        "from pathlib import Path",
        "",
        f"def {fn_name}({params_str}) -> str:",
        f'    """{doc}"""',
        "    from uiu.browser_connect import attach_default_browser",
        "    from uiu.browser_self_healing import resilient_browser_action",
        "",
        "    t_start = time.perf_counter()",
        "    logs = []",
        "    macro_file = Path(__file__)",
        "",
        "    # 1. Attach to user's running browser via CDP",
        "    session = attach_default_browser()",
        "    page = session.get_active_page()",
        f'    logs.append(f"已挂接日常浏览器，当前活动页面: {{page.title()[:30]}}")',
        "",
    ]

    # Navigate to start URL if specified
    if trajectory.start_url:
        lines.extend([
            f"    # Ensure start URL",
            f"    current_url = page.url",
            f"    start_url = {repr(trajectory.start_url)}",
            f"    if not current_url.startswith(start_url.split('?')[0]):",
            f"        page.goto(start_url, timeout=15000)",
            f'        logs.append(f"已导航至目标页面: {{start_url}}")',
            "",
        ])

    # Steps execution
    for i, step in enumerate(trajectory.steps, 1):
        action = step.get("action", "click")
        val = step.get("value", "")
        fp = step.get("fingerprint", {})
        target = step.get("target", "")

        # Check if value refers to a parameter variable
        if val in trajectory.parameters:
            val_code = val
        else:
            val_code = repr(val)

        step_meta_dict = {
            "action": action,
            "target": target,
            "value": "__PLACEHOLDER_VALUE__",
            "fingerprint": fp,
        }
        meta_json = json.dumps(step_meta_dict, ensure_ascii=False)
        meta_code = meta_json.replace('"__PLACEHOLDER_VALUE__"', val_code)

        lines.extend([
            f"    # Step {i}: {action} -> {repr(target or fp.get('text') or fp.get('testId'))}",
            f"    step_meta_{i} = {meta_code}",
            f"    res_{i} = resilient_browser_action(page, step_meta_{i}, macro_file_path=macro_file)",
            f"    if not res_{i}.get('success'):",
            f"        return f\"[error] 步骤 {i} ({action}) 执行失败: {{res_{i}.get('error')}}\"",
            f"    tier_{i} = res_{i}.get('tier', 'dom')",
            f"    if res_{i}.get('healed'):",
            f"        logs.append(f\"步骤 {i} 触发视觉自愈并成功执行 (通道: {{tier_{i}}})\")",
            f"    else:",
            f"        logs.append(f\"步骤 {i} 极速执行成功 (通道: {{tier_{i}}}, 选择器: {{res_{i}.get('selector_used')}})\")",
            "",
        ])

    # Assembly report
    lines.extend([
        "    elapsed_ms = (time.perf_counter() - t_start) * 1000.0",
        "    report = [",
        f'        f"### [Web Macro: {trajectory.name}] 执行完成 (总耗时: {{elapsed_ms:.1f}}ms / {{elapsed_ms/1000.0:.2f}}s)",',
        '        "**执行明细:**",',
        "    ]",
        "    for l in logs:",
        '        report.append("  * " + l)',
        '    return "\\n".join(report)',
        "",
    ])

    return "\n".join(lines)


def save_and_register_browser_macro(
    trajectory: BrowserTrajectory,
    save_dir: Path | None = None,
) -> tuple[str, Path]:
    """Compile trajectory into a Python script in workspace/macros/web/ and register dynamically."""
    code = compile_browser_trajectory_to_python(trajectory)
    fn_name = _clean_macro_identifier(trajectory.name)

    if save_dir is None:
        from .workspace import Workspace
        from .learning import _ws
        ws = _ws()
        root = ws.root if ws else Path.cwd()
        save_dir = root / "macros" / "web"

    save_dir.mkdir(parents=True, exist_ok=True)
    target_file = save_dir / f"{fn_name}.py"
    target_file.write_text(code, encoding="utf-8")

    # In-memory dynamic import
    spec = importlib.util.spec_from_file_location(fn_name, target_file)
    if spec and spec.loader:
        module = importlib.util.module_from_spec(spec)
        sys.modules[fn_name] = module
        spec.loader.exec_module(module)
        compiled_fn = getattr(module, fn_name, None)
        if callable(compiled_fn):
            COMPILED_BROWSER_MACROS[fn_name] = compiled_fn

    return fn_name, target_file


def run_browser_macro(name: str, **kwargs) -> str:
    """Run an existing compiled browser macro with zero thinking latency."""
    clean_name = _clean_macro_identifier(name)
    fn = COMPILED_BROWSER_MACROS.get(clean_name)

    if not fn:
        from .workspace import Workspace
        from .learning import _ws
        ws = _ws()
        root = ws.root if ws else Path.cwd()
        target_file = root / "macros" / "web" / f"{clean_name}.py"
        if target_file.exists():
            spec = importlib.util.spec_from_file_location(clean_name, target_file)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                sys.modules[clean_name] = module
                spec.loader.exec_module(module)
                fn = getattr(module, clean_name, None)
                if callable(fn):
                    COMPILED_BROWSER_MACROS[clean_name] = fn

    if not fn:
        return f"[error] 未找到已编译的浏览器宏: {name} (请确认 macros/web/{clean_name}.py 是否存在)"

    try:
        return fn(**kwargs)
    except Exception as e:
        return f"[error] 浏览器宏 '{name}' 执行异常: {type(e).__name__}: {e}"
