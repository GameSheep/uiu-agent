"""技能：skills list/install/search/add/edit + 内置技能同步（自原 commands.py 按域拆分；审计 §2.1）。"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import tools
from .config import (
    AppConfig,
    ChannelConfig,
    ModelConfig,
    config_yaml_path,
    ensure_workspace,
    load_config,
    parse_env_file,
    save_config,
    write_env_file,
)
from .workspace import load_workspace


# ---------- helpers ----------

from .cli_shared import (
    _ok_or_error,
    _print_err,
    _print_ok,
    _workspace,
)


def cmd_skills(args) -> int:
    ws = _workspace(args)
    skills_dir = ws / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)

    if args.action == "install":
        from .skill_installer import install_skill
        # 失败必须非 0：以前是 print(...) + return 0，DNS 挂了也报成功
        return _ok_or_error(install_skill(args.identifier, skills_dir,
                                          name_override=args.name, force=args.force))

    if args.action == "search":
        from .skill_installer import search_skills
        return _ok_or_error(search_skills(args.query, limit=args.limit))

    if args.action == "inspect":
        from .skill_installer import parse_identifier, find_skill_files, _http_get
        parsed = parse_identifier(args.identifier)
        if parsed["kind"] == "unknown":
            _print_err(f"无法识别: {args.identifier}")
            return 2
        files = find_skill_files(parsed)
        if not files or files[0].startswith("error:"):
            _print_err(files[0] if files else "未找到 SKILL.md")
            return 2
        for f in files[:3]:
            try:
                if f.startswith("http"):
                    content = _http_get(f).decode("utf-8")
                else:
                    owner, repo, branch = parsed["owner"], parsed["repo"], parsed["branch"]
                    url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{f}"
                    content = _http_get(url).decode("utf-8")
                print(f"=== {f} ===")
                print(content[:800])
                print("…" if len(content) > 800 else "")
            except Exception as e:
                _print_err(f"获取失败: {e}")
        print("\n安装: uiu skills install", args.identifier)
        return 0

    if args.action == "reload":
        # 真重载：重新掃磁盘 skills 并计数（下次对话 load_workspace 本来就会读盘，
        # 这里提前验证，坏文件立刻报错而不是拖死下次启动）
        try:
            from .workspace import load_workspace as _load_ws
            ws_obj = _load_ws(ws)
            print(f"[ok] skills 已重新加载（{len(ws_obj.skills)} 个，下次对话生效）")
        except Exception as e:
            _print_err(f"skills 重载失败: {type(e).__name__}: {e}")
            return 1
        return 0

    if args.action == "list":
        if not skills_dir.is_dir():
            print("(no skills directory)")
            return 0
        any_shown = False
        for d in sorted(skills_dir.iterdir()):
            if not d.is_dir():
                continue
            sk = d / "SKILL.md"
            if not sk.exists():
                continue
            text = sk.read_text(encoding="utf-8", errors="replace").splitlines()
            name = d.name
            desc = ""
            for line in text:
                if line.startswith("description:"):
                    desc = line.split(":", 1)[1].strip()
                    break
            print(f"  {name:<24} {desc[:70]}")
            any_shown = True
        if not any_shown:
            print("(no skills — try: uiu skills add echo)")
        return 0

    if args.action == "add":
        name = args.name
        target = skills_dir / name
        if target.exists():
            _print_err(f"技能已存在: {target}")
            return 2
        template = (
            f"---\nname: {name}\ndescription: TODO: describe when to use this skill.\n---\n\n"
            "exec: \n\n"
            "```tool_schema\n"
            "{\n"
            '  "type": "object",\n'
            '  "properties": {"input": {"type": "string"}},\n'
            '  "required": ["input"]\n'
            "}\n"
            "```\n"
        )
        target.mkdir(parents=True, exist_ok=True)
        (target / "SKILL.md").write_text(template, encoding="utf-8")
        _print_ok(f"已创建 {target / 'SKILL.md'}")
        print("edit it, then it'll be picked up on next `uiu` start")
        return 0

    if args.action == "edit":
        target = skills_dir / args.name / "SKILL.md"
        if not target.exists():
            _print_err(f"没有这个技能: {args.name}")
            return 2
        editor = os.environ.get("EDITOR", "notepad" if os.name == "nt" else "vi")
        try:
            subprocess.run([editor, str(target)], check=False)
        except FileNotFoundError:
            _print_err(f"找不到编辑器 '{editor}'，请设置 $EDITOR")
            return 2
        return 0

    if args.action == "path":
        print(skills_dir)
        return 0

    return 2


def _update_default_skills(ws: Path) -> int:
    """Sync default skills shipped with the package into workspace/skills/_default/."""
    import importlib.resources as resources
    try:
        pkg_root = resources.files("uiu")
    except Exception:
        pkg_root = None

    if pkg_root is None or not (pkg_root / "_default_skills").is_dir():
        print("(no default skills bundled)")
        return 0

    target = ws / "skills" / "_default"
    target.mkdir(parents=True, exist_ok=True)
    copied = 0
    for entry in (pkg_root / "_default_skills").iterdir():  # type: ignore[attr-defined]
        if not entry.is_dir():
            continue
        dest = target / entry.name
        if dest.exists():
            continue
        shutil.copytree(str(entry), str(dest))
        copied += 1
    _print_ok(f"已同步 {copied} 个内置技能到 {target}")
    return 0
