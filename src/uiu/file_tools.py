"""Universal File Management Tools.

Provides safe, rich file and directory manipulation:
- file_copy: copy files or directories
- file_move: move or rename files or directories
- file_get_content: read file with line slice and size options
- directory_list: list directory contents with details
- file_delete: delete file safely
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from ._sandbox import MAX_READ_BYTES, check_path


def file_copy(src: str, dst: str, overwrite: bool = False) -> str:
    """Copy a file or directory to a destination."""
    ok_src, msg_src, p_src = check_path(src)
    if not ok_src:
        return msg_src
    ok_dst, msg_dst, p_dst = check_path(dst, for_write=True)
    if not ok_dst:
        return msg_dst
    assert p_src is not None and p_dst is not None

    if not p_src.exists():
        return f"[error] 源文件或目录不存在: {p_src}"

    if p_dst.exists() and not overwrite:
        return f"[error] 目标已存在且未指定 overwrite: {p_dst}"

    try:
        p_dst.parent.mkdir(parents=True, exist_ok=True)
        if p_src.is_dir():
            if p_dst.exists() and overwrite:
                shutil.rmtree(p_dst)
            shutil.copytree(p_src, p_dst)
            return f"[ok] 成功复制目录: {p_src} -> {p_dst}"
        else:
            shutil.copy2(p_src, p_dst)
            return f"[ok] 成功复制文件: {p_src} -> {p_dst}"
    except Exception as e:
        return f"[error] 复制失败: {type(e).__name__}: {e}"


def file_move(src: str, dst: str, overwrite: bool = False) -> str:
    """Move or rename a file or directory."""
    ok_src, msg_src, p_src = check_path(src, for_write=True)
    if not ok_src:
        return msg_src
    ok_dst, msg_dst, p_dst = check_path(dst, for_write=True)
    if not ok_dst:
        return msg_dst
    assert p_src is not None and p_dst is not None

    if not p_src.exists():
        return f"[error] 源文件或目录不存在: {p_src}"

    if p_dst.exists():
        if not overwrite:
            return f"[error] 目标已存在且未指定 overwrite: {p_dst}"
        if p_dst.is_dir():
            shutil.rmtree(p_dst)
        else:
            p_dst.unlink()

    try:
        p_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(p_src), str(p_dst))
        return f"[ok] 成功移动: {p_src} -> {p_dst}"
    except Exception as e:
        return f"[error] 移动失败: {type(e).__name__}: {e}"


def file_get_content(path: str, start_line: int = 1, end_line: int | None = None, max_chars: int = 200000) -> str:
    """Read file content with optional line number range (1-indexed)."""
    ok, msg, p = check_path(path)
    if not ok:
        return msg
    assert p is not None

    if not p.exists():
        return f"[error] 文件不存在: {p}"
    if not p.is_file():
        return f"[error] 不是文件: {p}"

    try:
        # Check size limit
        size = p.stat().st_size
        if size > MAX_READ_BYTES and end_line is None:
            return f"[error] 文件过大 ({size // 1024}KB > {MAX_READ_BYTES // 1024}KB)，请指定 start_line 与 end_line 分片读取"

        with open(p, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        total_lines = len(lines)
        s_line = max(1, int(start_line or 1))
        e_line = min(total_lines, int(end_line or total_lines))

        if s_line > total_lines:
            return f"[ok] 文件共 {total_lines} 行，起始行 {s_line} 超出范围 (空内容)"

        selected = lines[s_line - 1 : e_line]
        result = "".join(selected)
        if len(result) > max_chars:
            result = result[:max_chars] + f"\n... (已截断，超出 {max_chars} 字符限制)"

        header = f"=== [{p.name}] (行 {s_line}-{e_line} / 共 {total_lines} 行) ===\n"
        return header + result
    except Exception as e:
        return f"[error] 读取文件失败: {type(e).__name__}: {e}"


def directory_list(path: str = ".", recursive: bool = False, max_depth: int = 2) -> str:
    """List contents of a directory with file sizes and type indicators."""
    ok, msg, p = check_path(path)
    if not ok:
        return msg
    assert p is not None

    if not p.exists():
        return f"[error] 目录不存在: {p}"
    if not p.is_dir():
        return f"[error] 不是目录: {p}"

    entries = []
    try:
        if not recursive:
            for item in sorted(p.iterdir()):
                prefix = "[DIR] " if item.is_dir() else "[FILE]"
                size_str = ""
                if item.is_file():
                    sz = item.stat().st_size
                    size_str = f" ({sz} bytes)" if sz < 1024 else f" ({sz / 1024:.1f} KB)"
                entries.append(f"  {prefix} {item.name}{size_str}")
        else:
            base_depth = len(p.parts)
            for root_dir, dirs, files in os.walk(p):
                curr_path = Path(root_dir)
                depth = len(curr_path.parts) - base_depth
                if depth >= max_depth:
                    dirs.clear()
                    continue
                indent = "  " * depth
                rel = curr_path.relative_to(p)
                if str(rel) != ".":
                    entries.append(f"{indent}[DIR] {rel}/")
                for f in sorted(files):
                    fpath = curr_path / f
                    sz = fpath.stat().st_size
                    size_str = f" ({sz} bytes)" if sz < 1024 else f" ({sz / 1024:.1f} KB)"
                    entries.append(f"{indent}  [FILE] {f}{size_str}")

        count_desc = f"共 {len(entries)} 项"
        return f"=== 目录清单: {p} ({count_desc}) ===\n" + "\n".join(entries[:100])
    except Exception as e:
        return f"[error] 列出目录失败: {type(e).__name__}: {e}"


def file_delete(path: str) -> str:
    """Safely delete a file."""
    ok, msg, p = check_path(path, for_write=True)
    if not ok:
        return msg
    assert p is not None

    if not p.exists():
        return f"[error] 文件不存在: {p}"
    if p.is_dir():
        return f"[error] {p} 是目录，为防意外仅支持删除普通文件"

    try:
        p.unlink()
        return f"[ok] 已删除文件: {p}"
    except Exception as e:
        return f"[error] 删除文件失败: {type(e).__name__}: {e}"


# Tool schemas
FILE_COPY_DEF = {
    "type": "function",
    "function": {
        "name": "file_copy",
        "description": "复制文件或文件夹到指定目标位置。",
        "parameters": {
            "type": "object",
            "properties": {
                "src": {"type": "string", "description": "源文件或目录路径"},
                "dst": {"type": "string", "description": "目标路径"},
                "overwrite": {"type": "boolean", "description": "是否覆盖已存在文件", "default": False},
            },
            "required": ["src", "dst"],
        },
    },
}

FILE_MOVE_DEF = {
    "type": "function",
    "function": {
        "name": "file_move",
        "description": "移动或重命名文件或文件夹。",
        "parameters": {
            "type": "object",
            "properties": {
                "src": {"type": "string", "description": "源文件或目录路径"},
                "dst": {"type": "string", "description": "目标路径"},
                "overwrite": {"type": "boolean", "description": "是否覆盖已存在文件", "default": False},
            },
            "required": ["src", "dst"],
        },
    },
}

FILE_GET_CONTENT_DEF = {
    "type": "function",
    "function": {
        "name": "file_get_content",
        "description": "获取文件内容，支持分行读取（start_line, end_line），避免大文件撑爆上下文。",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件路径"},
                "start_line": {"type": "integer", "description": "起始行号（从1开始）", "default": 1},
                "end_line": {"type": "integer", "description": "结束行号（可选）"},
                "max_chars": {"type": "integer", "description": "最多返回字符数", "default": 200000},
            },
            "required": ["path"],
        },
    },
}

DIRECTORY_LIST_DEF = {
    "type": "function",
    "function": {
        "name": "directory_list",
        "description": "列出指定文件夹内的子文件和目录列表，包含文件大小。",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "目录路径（默认当前工作区）", "default": "."},
                "recursive": {"type": "boolean", "description": "是否递归列出子文件夹", "default": False},
                "max_depth": {"type": "integer", "description": "递归最大深度（默认2）", "default": 2},
            },
        },
    },
}

def cleanup_temp_screenshots(directory: str = ".", pattern: str = "*.png", max_age_seconds: int = 0) -> str:
    """Clean up orphaned scratch/debug screenshots from the workspace/root directory."""
    import time
    from pathlib import Path
    target_p = Path(directory).resolve()
    if not target_p.is_dir():
        return f"[error] 目录不存在: {directory}"

    deleted_files = []
    total_freed_bytes = 0
    now = time.time()

    scratch_prefixes = ("wx_", "desktop_", "chatgpt_", "shot", "dbg_", "check_", "tmp_", "menu_", "wechat_")
    
    for f in target_p.glob(pattern):
        if not f.is_file():
            continue
        is_scratch = any(f.name.lower().startswith(pre) for pre in scratch_prefixes) or (f.name.lower().endswith((".png", ".jpg", ".jpeg")) and directory == ".")
        if not is_scratch:
            continue
        if max_age_seconds > 0:
            age = now - f.stat().st_mtime
            if age < max_age_seconds:
                continue
        try:
            sz = f.stat().st_size
            f.unlink()
            deleted_files.append(f.name)
            total_freed_bytes += sz
        except Exception:
            pass

    freed_mb = total_freed_bytes / (1024 * 1024)
    return f"[ok] 已清理 {len(deleted_files)} 个临时截图文件，释放空间 {freed_mb:.2f} MB"


FILE_DELETE_DEF = {
    "type": "function",
    "function": {
        "name": "file_delete",
        "description": "删除指定文件。",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "待删除的文件路径"},
            },
            "required": ["path"],
        },
    },
}

CLEANUP_TEMP_SCREENSHOTS_DEF = {
    "type": "function",
    "function": {
        "name": "cleanup_temp_screenshots",
        "description": "清理运行和测试遗留的临时/调试截图文件，释放磁盘空间。",
        "parameters": {
            "type": "object",
            "properties": {
                "directory": {"type": "string", "description": "待清理目录（默认当前根目录）", "default": "."},
                "pattern": {"type": "string", "description": "文件名匹配模式", "default": "*.png"},
                "max_age_seconds": {"type": "integer", "description": "最小时长（秒），默认0表示立即清理所有孤立截图", "default": 0},
            },
        },
    },
}

FILE_TOOLS: dict[str, dict] = {
    "file_copy": {"def": FILE_COPY_DEF, "fn": file_copy},
    "file_move": {"def": FILE_MOVE_DEF, "fn": file_move},
    "file_get_content": {"def": FILE_GET_CONTENT_DEF, "fn": file_get_content},
    "directory_list": {"def": DIRECTORY_LIST_DEF, "fn": directory_list},
    "file_delete": {"def": FILE_DELETE_DEF, "fn": file_delete},
    "cleanup_temp_screenshots": {"def": CLEANUP_TEMP_SCREENSHOTS_DEF, "fn": cleanup_temp_screenshots},
}


def file_tool_defs() -> list[dict]:
    return [t["def"] for t in FILE_TOOLS.values()]
