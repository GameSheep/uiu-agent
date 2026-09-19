"""运维：doctor / update / publish / serve（自原 commands.py 按域拆分；审计 §2.1）。"""

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
    _is_git_source_install,
    _print_err,
    _print_ok,
    _workspace,
)

from .cli_skills import (
    _update_default_skills,
)


def cmd_doctor(args) -> int:
    import dataclasses

    from . import cli_io
    from .doctor import _all_checks, run_doctor
    ws = _workspace(args)
    kwargs = {"lint": getattr(args, "lint", False),
              "fix": getattr(args, "fix", False),
              "yes": getattr(args, "yes", False),
              "install_deps": getattr(args, "install_deps", False)}
    if not cli_io.json_mode():
        return run_doctor(ws, **kwargs)

    # JSON 模式：人读过程走 stderr，stdout 只留一个信封
    rc = run_doctor(ws, out=cli_io.progress, **kwargs)
    findings = [dataclasses.asdict(f) for f in _all_checks(ws)]
    cli_io.result("doctor", ok=(rc == 0),
                  data={"findings": findings, "exit_code": rc, **kwargs},
                  error="" if rc == 0 else "存在未解决的问题")
    return rc


def cmd_update(args) -> int:
    ws = _workspace(args)
    if args.what == "self":
        if not _is_git_source_install():
            # PyPI / npm 安装：无 git 仓库，直接 pip 升级当前环境
            import importlib.metadata as _md
            try:
                cur = _md.version("uiu")
            except Exception:
                cur = "?"
            from .cli_io import step
            idx = os.environ.get("UIU_PIP_INDEX", "")
            cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "--quiet",
                   "--disable-pip-version-check", "uiu"]
            if idx:
                cmd += ["-i", idx]
            with step(f"从 PyPI 升级 uiu（当前 {cur}）"):
                r = subprocess.run(cmd, check=False)
                if r.returncode != 0:
                    _print_err("pip 升级失败（网络/镜像问题？）")
                    return 1
            try:
                new = _md.version("uiu")
            except Exception:
                new = "?"
            _print_ok(f"更新完成 {cur} → {new}，重启 uiu 生效")
            print("  (npm 安装时也可用: npm update -g uiu)")
            return 0
        if getattr(args, "no_pull", False):
            # skip git pull, still verify + staged install
            from .safe_update import staged_install, ensure_backup_point
            import os
            repo_root = Path(__file__).resolve().parent.parent.parent
            src_dir = repo_root / "src" / "uiu"
            tag = ensure_backup_point(repo_root)
            if tag:
                print(f"· 已创建回滚点: git tag {tag}")
            print("· 在隔离环境验证安装（不碰当前运行环境）…")
            ok, msg = staged_install(repo_root, src_dir)
            if not ok:
                _print_err(f"更新验证失败，已回滚（当前环境未动）:\n{msg}")
                return 1
            print(f"· 验证通过 ({msg})，应用更新…")
            rc = subprocess.run(
                [sys.executable, "-m", "pip", "install", "-e", str(repo_root), "--quiet"],
                check=False,
            )
            if rc.returncode != 0:
                _print_err("应用更新失败")
                return 1
            _print_ok("更新完成！重启 uiu 生效")
            return 0
        from .safe_update import safe_self_update
        return safe_self_update()
    if args.what == "skills":
        return _update_default_skills(ws)
    return 2


def cmd_publish(args) -> int:
    """Build wheel + sdist and upload to PyPI (or TestPyPI with --test).

    --dry-run: build + inspect wheel contents locally, upload nothing.
    """
    dry_run = bool(getattr(args, "dry_run", False))

    # version-consistency gate (v1.0 release discipline)
    ok, ver = _verify_version_consistency()
    if not ok:
        _print_err(f"发布被拦下: {ver}")
        print("  fix version mismatch, then retry")
        return 2
    print(f"· version consistency ok ({ver})")

    token = args.token or os.environ.get("PYPI_TOKEN") or os.environ.get("TWINE_PASSWORD")
    if not token and not dry_run:
        _print_err("没有 PyPI token：设置 PYPI_TOKEN 环境变量，或用 --token <token> 传入")
        print("  create one at https://pypi.org/manage/account/token/")
        return 2

    # 1. build（慢步骤给进度与耗时，脚本模式下进度走 stderr）
    from .cli_io import step

    # dry-run 只到「本地构建 + 检查 wheel」为止，**不需要 twine** —— 它的依赖树很重
    # （本机实测冷装 15 分钟以上），会让「发布前先验一遍」这件事没人愿意做。
    tools_needed = ["build"] if dry_run else ["build", "twine"]
    with step("安装构建工具 " + "/".join(tools_needed)):
        rc = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet", *tools_needed],
            check=False,
        )
        if rc.returncode != 0:
            _print_err("安装构建依赖 " + "/".join(tools_needed) + " 失败")
            return 1
    with step("构建 sdist + wheel"):
        rc = subprocess.run([sys.executable, "-m", "build", "--sdist", "--wheel"], check=False)
        if rc.returncode != 0:
            _print_err("构建失败 —— 先修上面的错误再重试")
            return 1

    # inspect built artifacts (ensure default workspace/skills packaged)
    dist_dir = Path("dist")
    wheels = sorted(dist_dir.glob("*.whl"))
    if not wheels:
        _print_err("dist/ 里没有产出 wheel")
        return 1
    wheel = wheels[-1]
    print(f"· built {wheel.name}")
    if dry_run:
        import zipfile
        names = []
        with zipfile.ZipFile(wheel) as zf:
            names = sorted(n for n in zf.namelist() if not n.startswith("uiu-"))
        want = ["uiu/_default_workspace/SOUL.md", "uiu/_default_workspace/IDENTITY.md"]
        missing = [w for w in want if not any(n.endswith(w.split('/', 1)[1]) for n in names)]
        print(f"· wheel contains {len(names)} files")
        if missing:
            print("  WARNING missing from wheel:", missing)
        else:
            print("  ok: default workspace bundled")
        print("· dry-run complete — nothing uploaded")
        return 0

    # 2. upload
    if args.test:
        repo = "https://test.pypi.org/legacy/"
        print(f"· uploading to TestPyPI…")
    else:
        repo = "https://upload.pypi.org/legacy/"
        print(f"· uploading to PyPI…")

    # expand dist/* glob explicitly (filtered by current version)
    dist_dir = Path("dist")
    artifacts = sorted(dist_dir.glob(f"*{ver}*.whl")) + sorted(dist_dir.glob(f"*{ver}*.tar.gz"))
    if not artifacts:
        _print_err("dist/ 里没有构建产物")
        return 1
    upload_env = {
        **os.environ,
        "TWINE_USERNAME": "__token__",
        "TWINE_PASSWORD": token,
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    rc = subprocess.run(
        [
            sys.executable,
            "-m",
            "twine",
            "upload",
            "--repository-url",
            repo,
            *map(str, artifacts),
            "--non-interactive",
            "--disable-progress-bar",
        ],
        env=upload_env,
        check=False,
    )
    if rc.returncode != 0:
        _print_err("上传失败 —— 先修上面的错误再重试")
        return 1

    if args.test:
        print("  done! try: pip install --index-url https://test.pypi.org/simple/ uiu")
    else:
        print("  done! try: pip install uiu   or   pipx run uiu")
    return 0


def cmd_serve(args) -> int:
    ws = _workspace(args)
    cfg = load_config(ws)
    from .gateway import Gateway
    from .workspace import load_workspace
    ws_obj = load_workspace(ws)
    gw = Gateway(cfg, ws_obj)
    reason = gw.run(port=args.port, host=getattr(args, "host", "") or "")
    if reason:
        # 网关没能起来时必须非 0：否则脚本/守护进程会以为服务在跑
        _print_err(reason)
        return 2
    return 0


def _verify_version_consistency() -> tuple[bool, str]:
    """pyproject.toml vs src/uiu/__init__.py must agree (v1.0 publish gate)."""
    import tomllib
    from pathlib import Path as _P
    here = _P(__file__).resolve().parent.parent.parent  # src/uiu -> repo root
    pyproject = here / "pyproject.toml"
    init = here / "src" / "uiu" / "__init__.py"
    if not pyproject.exists() or not init.exists():
        return False, f"cannot locate repo files ({pyproject}, {init})"
    try:
        with open(pyproject, "rb") as f:
            py_ver = tomllib.load(f)["project"]["version"]
    except Exception as e:
        return False, f"pyproject.toml unreadable: {e}"
    txt = init.read_text(encoding="utf-8")
    import re as _re
    m = _re.search(r"__version__\s*=\s*[\"']([^\"']+)[\"']", txt)
    if not m:
        return False, "src/uiu/__init__.py missing __version__"
    if m.group(1) != py_ver:
        return False, f"version mismatch: pyproject={py_ver} vs __init__={m.group(1)}"
    return True, py_ver
