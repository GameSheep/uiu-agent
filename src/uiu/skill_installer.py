"""Skill installer — install skills from GitHub repos / URLs (Hermes skills install).

支持的 identifier 格式：
- https://github.com/owner/repo             -> 取仓库里 SKILL.md（根目录或 skills/ 子目录）
- https://github.com/owner/repo/tree/main/skills/xxx -> 指定目录
- https://raw.githubusercontent.com/.../SKILL.md -> 直接 SKILL.md URL
- owner/repo                                -> 简写 GitHub

安装到 workspace/skills/<name>/，重启 uiu（或 TUI /skills reload）即生效。
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path

GITHUB_API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"


# ---------- identifier parsing ----------

def parse_identifier(identifier: str) -> dict:
    """Parse a skill identifier into {kind, owner, repo, path, url}."""
    ident = identifier.strip()

    # direct raw URL to SKILL.md
    if ident.startswith("https://raw.githubusercontent.com/"):
        return {"kind": "raw", "url": ident}

    # github.com URL (repo or tree path)
    m = re.match(r"https://github\.com/([^/]+)/([^/]+)(?:/tree/([^/]+)(/.*)?)?$", ident)
    if m:
        owner, repo = m.group(1), m.group(2).rstrip("/")
        branch = m.group(3) or "main"
        path = (m.group(4) or "").strip("/")
        return {"kind": "github", "owner": owner, "repo": repo, "branch": branch, "path": path}

    # owner/repo shorthand
    m = re.match(r"^([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)$", ident)
    if m:
        owner, repo = m.group(1), m.group(2)
        return {"kind": "github", "owner": owner, "repo": repo, "branch": "main", "path": ""}

    # plain http(s) URL to a SKILL.md
    if ident.startswith("http"):
        return {"kind": "url", "url": ident}

    return {"kind": "unknown"}


# ---------- fetching ----------

def _http_get(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "uiu/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _github_contents(owner: str, repo: str, path: str, branch: str) -> list[dict]:
    """List a GitHub repo dir via Contents API."""
    url = f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}?ref={branch}"
    data = json.loads(_http_get(url).decode("utf-8"))
    return data if isinstance(data, list) else []


def _github_tree(owner: str, repo: str, branch: str) -> list[dict]:
    """Get full repo tree (for finding SKILL.md anywhere)."""
    url = f"{GITHUB_API}/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
    data = json.loads(_http_get(url).decode("utf-8"))
    return data.get("tree", [])


# ---------- discovery ----------

def find_skill_files(parsed: dict) -> list[str]:
    """Locate SKILL.md files for a parsed identifier. Returns list of repo paths."""
    if parsed["kind"] in ("raw", "url"):
        return [parsed["url"]]
    owner, repo, branch, path = parsed["owner"], parsed["repo"], parsed["branch"], parsed["path"]
    try:
        if path:
            # explicit dir: look for SKILL.md inside
            tree = _github_tree(owner, repo, branch)
            return [
                t["path"] for t in tree
                if t["type"] == "blob" and t["path"].endswith("SKILL.md") and t["path"].startswith(path)
            ]
        # whole repo: find SKILL.md in root or skills/<name>/SKILL.md
        tree = _github_tree(owner, repo, branch)
        candidates = [
            t["path"] for t in tree
            if t["type"] == "blob" and t["path"].endswith("SKILL.md")
        ]
        # prefer root SKILL.md, then skills/ paths
        root = [c for c in candidates if "/" not in c]
        sub = [c for c in candidates if c.startswith(("skills/", ".agents/skills/", ".claude/skills/"))]
        return (root + sub) or candidates
    except Exception as e:
        return [f"error: {e}"]


# ---------- install ----------

def install_skill(identifier: str, skills_dir: Path, name_override: str = "", force: bool = False) -> str:
    """Install a skill into skills_dir. Returns human-readable result."""
    parsed = parse_identifier(identifier)
    if parsed["kind"] == "unknown":
        return f"[error] 无法识别 identifier: {identifier}\n  支持: GitHub URL / owner/repo / SKILL.md URL"

    files = find_skill_files(parsed)
    if not files or files[0].startswith("error:"):
        err = files[0] if files else "未找到 SKILL.md"
        return f"[error] {err}"

    installed = []
    for file_path in files:
        try:
            if file_path.startswith("http"):
                content = _http_get(file_path).decode("utf-8")
            else:
                owner, repo, branch = parsed["owner"], parsed["repo"], parsed["branch"]
                url = f"{RAW}/{owner}/{repo}/{branch}/{file_path}"
                content = _http_get(url).decode("utf-8")
        except urllib.error.HTTPError as e:
            return f"[error] 下载失败 {file_path}: HTTP {e.code}"
        except Exception as e:
            return f"[error] 下载失败: {type(e).__name__}: {e}"

        if "---" not in content or "name:" not in content:
            # still accept bare SKILL.md, derive name from path
            name = name_override or Path(file_path).parent.name or Path(file_path).stem
        else:
            m = re.search(r"^name:\s*(\S+)", content, re.MULTILINE)
            name = name_override or (m.group(1) if m else Path(file_path).parent.name)

        safe = re.sub(r"[^a-z0-9_-]", "_", name.lower()).strip("_")
        target = skills_dir / safe
        if target.exists() and not force:
            return f"[error] 技能 '{safe}' 已存在（用 --force 覆盖）"
        target.mkdir(parents=True, exist_ok=True)
        (target / "SKILL.md").write_text(content, encoding="utf-8")
        installed.append(safe)

    if not installed:
        return "[error] 没有可安装的技能"
    names = ", ".join(installed)
    return f"[ok] 已安装: {names}\n  位置: {skills_dir}\n  重启 uiu 生效（或 TUI 里 /skills reload）"


# ---------- search (GitHub code search) ----------

def search_skills(query: str, limit: int = 10) -> str:
    """Search GitHub for repos with SKILL.md matching query."""
    try:
        import urllib.parse
        url = f"{GITHUB_API}/search/repositories?q={urllib.parse.quote(query + ' agent skills')}&sort=stars&per_page={limit}"
        data = json.loads(_http_get(url).decode("utf-8"))
    except Exception as e:
        return f"[error] 搜索失败: {type(e).__name__}: {e}"

    items = data.get("items", [])
    if not items:
        return "(没有结果)"
    lines = []
    for it in items[:limit]:
        desc = (it.get("description") or "")[:80]
        lines.append(f"  {it['full_name']:<40} ⭐{it.get('stargazers_count', 0)}  {desc}")
    lines.append("")
    lines.append("安装: uiu skills install <owner/repo>")
    return "\n".join(lines)