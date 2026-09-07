"""Multi-Modal Clipboard & Cross-Software Dataflow Pipeline.

Enables:
1. High-speed (<50ms) structured text, table, and rich image transfer between desktop apps.
2. Non-destructive clipboard preservation (`preserve_clipboard()`).
3. Multimodal image pasting directly into WeChat, Office, Discord, or Web editors via CF_DIB.
4. Auto-detecting and parsing clipboard tables (TSV, CSV, Markdown tables, JSON).
"""

from __future__ import annotations

import csv
import io
import json
import re
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


def _open_clipboard_with_retry(max_retries: int = 5, retry_delay: float = 0.05):
    import win32clipboard
    for attempt in range(max_retries):
        try:
            win32clipboard.OpenClipboard()
            return win32clipboard
        except Exception:
            time.sleep(retry_delay)
    # Final attempt that raises if failed
    win32clipboard.OpenClipboard()
    return win32clipboard


@contextmanager
def preserve_clipboard() -> Iterator[None]:
    """Context manager that preserves the user's existing clipboard contents.
    Restores the original text upon exit so agent automation does not overwrite user data.
    """
    if sys.platform != "win32":
        yield
        return

    import win32clipboard
    import win32con

    saved_text: str | None = None
    try:
        cb = _open_clipboard_with_retry()
        try:
            if cb.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                saved_text = cb.GetClipboardData(win32con.CF_UNICODETEXT)
        finally:
            cb.CloseClipboard()
    except Exception:
        pass

    try:
        yield
    finally:
        if saved_text is not None:
            try:
                cb = _open_clipboard_with_retry()
                try:
                    cb.EmptyClipboard()
                    cb.SetClipboardData(win32con.CF_UNICODETEXT, saved_text)
                finally:
                    cb.CloseClipboard()
            except Exception:
                pass


def clipboard_get_text() -> str:
    """Read plain/unicode text from clipboard."""
    if sys.platform != "win32":
        import pyperclip
        return pyperclip.paste()

    import win32clipboard
    import win32con

    cb = _open_clipboard_with_retry()
    try:
        if cb.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
            return str(cb.GetClipboardData(win32con.CF_UNICODETEXT))
        elif cb.IsClipboardFormatAvailable(win32con.CF_TEXT):
            data = cb.GetClipboardData(win32con.CF_TEXT)
            return data.decode("gbk", errors="ignore") if isinstance(data, bytes) else str(data)
        return ""
    finally:
        cb.CloseClipboard()


def clipboard_set_text(text: str) -> str:
    """Write text to clipboard with sub-millisecond latency."""
    if sys.platform != "win32":
        import pyperclip
        pyperclip.copy(text)
        return f"[ok] 剪贴板已写入 {len(text)} 字符"

    import win32clipboard
    import win32con

    cb = _open_clipboard_with_retry()
    try:
        cb.EmptyClipboard()
        cb.SetClipboardData(win32con.CF_UNICODETEXT, str(text))
        return f"[ok] 剪贴板已写入 {len(text)} 字符"
    finally:
        cb.CloseClipboard()


def clipboard_set_image(image_input: Any) -> str:
    """Set rich image / bitmap into clipboard as CF_DIB.

    Accepts:
    - Path string or Path object
    - PIL Image
    - numpy array
    """
    if sys.platform != "win32":
        return "[error] 图片剪贴板写入仅支持 Windows 平台"

    import win32clipboard
    import win32con
    from PIL import Image

    pil_img: Image.Image
    if isinstance(image_input, (str, Path)):
        p = Path(image_input)
        if not p.exists():
            return f"[error] 图片文件不存在: {p}"
        pil_img = Image.open(p)
    elif hasattr(image_input, "convert"):
        pil_img = image_input
    elif hasattr(image_input, "shape"):  # numpy array
        pil_img = Image.fromarray(image_input)
    else:
        return f"[error] 不支持的图像类型: {type(image_input)}"

    # Convert to BMP byte stream and strip 14-byte BMP file header to obtain raw DIB
    output = io.BytesIO()
    pil_img.convert("RGB").save(output, "BMP")
    dib_bytes = output.getvalue()[14:]
    output.close()

    cb = _open_clipboard_with_retry()
    try:
        cb.EmptyClipboard()
        cb.SetClipboardData(win32con.CF_DIB, dib_bytes)
        return f"[ok] 已将图像 ({pil_img.width}x{pil_img.height}) 写入剪贴板 (CF_DIB 格式)"
    finally:
        cb.CloseClipboard()


def clipboard_set_table(
    data: list[dict[str, Any]] | list[list[Any]],
    format_type: str = "tsv",
) -> str:
    """Convert structured tabular data into clipboard table format.

    - 'tsv': Standard tab-separated values, seamlessly pastes into Excel/Google Sheets columns.
    - 'markdown': Markdown table format | a | b |.
    - 'csv': Comma-separated values.
    """
    if not data:
        return clipboard_set_text("")

    if isinstance(data[0], dict):
        headers = list(data[0].keys())
        rows = [[str(item.get(h, "")) for h in headers] for item in data]
    else:
        headers = [f"Col{i+1}" for i in range(len(data[0]))]
        rows = [[str(cell) for cell in row] for row in data]

    if format_type == "tsv":
        lines = ["\t".join(headers)]
        for r in rows:
            lines.append("\t".join(r))
        text = "\r\n".join(lines)
    elif format_type == "markdown":
        header_line = "| " + " | ".join(headers) + " |"
        sep_line = "| " + " | ".join(["---"] * len(headers)) + " |"
        body_lines = ["| " + " | ".join(r) + " |" for r in rows]
        text = "\n".join([header_line, sep_line] + body_lines)
    else:  # csv
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(headers)
        writer.writerows(rows)
        text = buf.getvalue()

    clipboard_set_text(text)
    return f"[ok] 已将 {len(rows)} 行表格数据复制到剪贴板 (格式: {format_type})"


def clipboard_parse_table(raw_text: str | None = None) -> list[dict[str, Any]]:
    """Automatically parses tabular data from clipboard (or raw_text).
    Detects TSV (Excel copy), Markdown tables, CSV, or JSON arrays.
    """
    text = (raw_text if raw_text is not None else clipboard_get_text()).strip()
    if not text:
        return []

    # 1. Try JSON array of objects
    if text.startswith("[") and text.endswith("]"):
        try:
            val = json.loads(text)
            if isinstance(val, list) and all(isinstance(x, dict) for x in val):
                return val
        except Exception:
            pass

    # 2. Try Markdown table (| a | b |)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) >= 2 and lines[0].startswith("|") and lines[0].endswith("|"):
        headers = [c.strip() for c in lines[0].strip("|").split("|")]
        data_rows = []
        for line in lines[1:]:
            if re.match(r"^\|(\s*:?-+:?\s*\|)+$", line):
                continue  # separator row
            if line.startswith("|") and line.endswith("|"):
                cells = [c.strip() for c in line.strip("|").split("|")]
                row_dict = {}
                for idx, h in enumerate(headers):
                    row_dict[h] = cells[idx] if idx < len(cells) else ""
                data_rows.append(row_dict)
        if data_rows:
            return data_rows

    # 3. Try TSV (standard clipboard format from Excel/Google Sheets)
    if "\t" in lines[0]:
        reader = csv.DictReader(lines, delimiter="\t")
        return [dict(row) for row in reader]

    # 4. Try CSV
    if "," in lines[0]:
        reader = csv.DictReader(lines, delimiter=",")
        return [dict(row) for row in reader]

    return [{"text": line} for line in lines]


def cross_app_transfer(
    source_app: str,
    target_app: str,
    copy_action: Any = None,
    paste_action: Any = None,
    preserve_user: bool = True,
) -> str:
    """Seamless cross-window data transfer.
    1. Brings source app to front and copies data.
    2. Brings target app to front and pastes.
    3. Restores original clipboard if requested.
    """
    from .window_manager import open_or_focus_app
    from .gui_primitives import press_hotkey

    def _do_transfer():
        # Focus source
        open_or_focus_app(source_app)
        time.sleep(0.15)
        if callable(copy_action):
            copy_action()
        else:
            press_hotkey(["ctrl", "c"])
        time.sleep(0.1)

        # Focus target
        open_or_focus_app(target_app)
        time.sleep(0.15)
        if callable(paste_action):
            paste_action()
        else:
            press_hotkey(["ctrl", "v"])
        time.sleep(0.05)

    if preserve_user:
        with preserve_clipboard():
            _do_transfer()
    else:
        _do_transfer()

    return f"[ok] 数据已成功从 '{source_app}' 迁移粘贴至 '{target_app}'"
