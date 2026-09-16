"""把文本写进系统剪贴板（pyperclip → Windows Set-Clipboard 兜底）。

UI 不可用剪贴板时返回 (False, 原因)，调用方据此给用户提示而不是静默失败。
"""

from __future__ import annotations

import subprocess
import sys


def copy_text(text: str) -> tuple[bool, str]:
    """Copy *text* to the clipboard. Returns (ok, detail)."""
    if not text:
        return False, "没有可复制的内容"
    try:
        import pyperclip
        pyperclip.copy(text)
        return True, "pyperclip"
    except Exception:
        pass
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "$input | Set-Clipboard"],
                input=text, text=True, timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                check=True,
            )
            return True, "Set-Clipboard"
        except Exception as exc:  # noqa: BLE001
            return False, f"{type(exc).__name__}: {exc}"
    return False, "当前平台没有可用的剪贴板实现"
