# 发版清单（0.2.0b1 起）

> 一次发版 = **PyPI + npm 两条通道 + 发布后验证**。任何一步没做，用户侧就还是旧版本。
> 本文件是清单而不是教程：每一步都给了**可复制的命令**和**验收标准**。

## 0. 发布前真机验证记录（2026-09-19，本机实测）

发版前这些路径都**真的跑过一遍**（不是靠单测推断），结果与发现的 bug 如下：

| 路径 | 怎么跑的 | 结果 |
|---|---|---|
| 全新 venv 装核心依赖 | 3.12/3.13 全新 venv `pip install -e .` | **132 秒 / 31 个包**（此前整套依赖 30 分钟未装完） |
| wheel → 全新 3.12 venv → 冒烟 | `pip wheel` → 装 → version/init/doctor/show/TUI pilot | 全通；wheel 含 131 文件（默认 workspace/skills/LICENSE 都在） |
| npm 真实产物 | `npm pack` tarball 解包 → postinstall → 启动器 | 135 秒装完，`uiu 0.2.0b1` 与 `--json` 正常 |
| 发布门禁 | `uiu publish --dry-run` | **21 秒** rc=0（版本一致性 → 构建 → 检查 126 文件） |
| 网关 | 真起 serve + 真发 HTTP | 无/错 token → 401，对 token → 200；拒绝事件进审计 |
| 备份/恢复 | backup → 破坏 → restore --yes | 恢复 8 文件、内容一致、配置回滚、自动 pre-restore 快照 |
| cron / daemon | 真起 daemon，加一次到期任务 | 任务被自动执行；日志含 **daily backup** 与 cron tick |
| CLI 全命令 | 21 条命令在 `PYTHONIOENCODING=gbk` 下扫荡 | 0 崩溃（修复 2 处：`publish` 的 ✓、`skills search` 的 ⭐） |

**这一节的存在本身就是教训**：上面几乎每一行都查出过真 bug（302/文件名/GBK/递归强删/静默返回 0…），
而它们在单测里全都看不见。发版前请至少重跑一遍**你能跑的那些**。

## 0.1 三条铁律

1. **版本号四处锁步**：`pyproject.toml` / `src/uiu/__init__.py` / `npm/package.json` / `CHANGELOG.md`。
   由 `tests/test_packaging_contract.py::test_version_is_single_source` 守着，跑不过就不许发。
2. **npm 与 PyPI 的版本号写法不同**：npm 用 semver（`0.2.0-b1`），PyPI 用 PEP 440（`0.2.0b1`）。
   映射由 `npm/lib/version.js` 负责（`install.js` 用它拼 `pip install uiu==<version>`）。
   **发预发布版时特别容易踩**：`pip install uiu==0.2.0-b1` 会直接 no matching distribution。
3. **先本地全绿再谈发布**：全量测试 + 冒烟 + 生成物一致性，缺一不可。

## 1. 前置检查（本地，约 15 分钟）

```powershell
# ① 全量测试（不要只跑改动文件：竞态只在全量负载下暴露）
.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider

# ② 覆盖率门槛（当前 58；实测 60.2%）
.venv\Scripts\python.exe -m pytest tests -q --cov=uiu --cov-fail-under=58

# ③ CLI 冒烟
.venv\Scripts\python.exe cli_smoke.py

# ④ 生成物一致性（工具文档 / 平台矩阵 由脚本生成，过期会被 CI 拦下）
.venv\Scripts\python.exe scripts/gen_tools_doc.py --check
.venv\Scripts\python.exe scripts/gen_platform_doc.py --check

# ⑤ 版本号与 npm↔PyPI 映射
.venv\Scripts\python.exe -m pytest tests/test_packaging_contract.py -q
node npm/lib/version.js            # 映射自检（6 条用例）

# ⑥ 界面预览（改了 TUI 才需要）
.venv\Scripts\python.exe scripts/tui_preview.py
```

**验收**：以上命令全部 rc=0，且 `git status` 干净。

## 2. 写 CHANGELOG

- `## [Unreleased]` 里的内容整体移到新的 `## [<version>] - <YYYY-MM-DD>` 小节下；
- 顶部留一个空的 `## [Unreleased]`（写「（暂无）」）；
- 分类用 Keep a Changelog 的 Added / Changed / Fixed / Security / Removed。

**验收**：`test_version_is_single_source` 通过（它会检查 CHANGELOG 里有对应版本小节）。

## 3. 推送（本仓库的沙箱限制）

```powershell
git ls-remote origin          # 先探连通性
git push origin master
git push origin --tags
```

> 本仓库开发沙箱里 `git push` 不可用（`ssh.exe` 无法创建信号管道，Win32 error 5），
> **必须在普通终端执行**。CI 从 GitHub 拉代码，不推送就不会跑。

**验收**：`git rev-list --count origin/master..master` 输出 `0`。

## 4. PyPI 通道

```powershell
# 4.1 token：https://pypi.org/manage/account/token/ （首次）
$env:PYPI_TOKEN = "pypi-..."

# 4.2 先干跑：本地构建 + 检查 wheel 内容（不传任何东西；实测 21 秒）
.venv\Scripts\uiu.exe publish --dry-run

# 4.3 正式发布（内部会做版本一致性校验 + build + twine upload）
.venv\Scripts\uiu.exe publish
```

**验收（发布后立刻做，别等用户报错）**：

```powershell
$tmp = "$env:TEMP\uiu-release-check"; Remove-Item -Recurse -Force $tmp -EA SilentlyContinue
python -m venv $tmp
& "$tmp\Scripts\python.exe" -m pip install --upgrade pip
& "$tmp\Scripts\python.exe" -m pip install uiu==0.2.0b1     # ← 必须是 PyPI 上真实存在的号
& "$tmp\Scripts\python.exe" -m uiu.main version              # 期望输出 uiu 0.2.0b1
& "$tmp\Scripts\python.exe" -m uiu.main doctor --lint        # 缺 key 会 rc=1，但不应崩
```

## 5. npm 通道

```powershell
cd npm
npm login                     # 首次
npm publish                   # 版本与 PyPI 锁步（注意 semver 写法）
```

**验收**：

```powershell
npm view uiu-agent version                    # 期望 0.2.0-b1
# 端到端（本仓库已固化）：会在临时 UIU_HOME 里装一遍并跑启动器
powershell -ExecutionPolicy Bypass -File ..\scripts\verify_npm_install.ps1
```

**发布产物级验收（推荐，能进 CI 且不依赖 npm 的全局安装）**：直接解包 `npm pack` 出来的
tarball，按 npm 的布局摆好，然后跑 postinstall 与启动器——验证的是**用户真正拿到的东西**：

```powershell
$prefix = "<临时目录>"; New-Item -ItemType Directory "$prefix\node_modules" -Force
cd npm; npm pack --pack-destination $prefix
tar -xzf "$prefix\uiu-agent-0.2.0-b1.tgz" -C "$prefix\node_modules"; Rename-Item "$prefix\node_modules\package" "$prefix\node_modules\uiu-agent"
$env:UIU_HOME = "$prefix\home"
node "$prefix\node_modules\uiu-agent\bin\install.js"        # = postinstall
node "$prefix\node_modules\uiu-agent\bin\uiu.js" version     # 期望 uiu 0.2.0b1
```

> 这一步抓出过一个真 bug：`package.json` 的 `files` 白名单曾经只有 `["bin/"]`，
> 于是 `lib/version.js` 不随包发布 → 用户装完 `require` 失败。现在由
> `tests/test_npm_package.py` 守着（tarball 必须覆盖运行时 require 的每个文件）。

> 中国网络环境可加镜像：`$env:UIU_PIP_INDEX="https://pypi.tuna.tsinghua.edu.cn/simple"`；
> 内置 Python 下载可走 `UIU_PYTHON_MIRROR`。

## 6. 发布后

- [ ] GitHub 打 tag 并写 Release（把 CHANGELOG 对应小节贴过去）
- [ ] 在干净机器上装一次（**换台机器**：本机可能被开发环境的依赖掩盖）
- [ ] 观察 24 小时的 issue / 崩溃反馈；预发布版**不要**在 README 首屏宣传
- [ ] 确认 `pip install uiu`（不带版本号）仍然装到**上一个稳定版**——
      预发布版只对显式指定的用户可见，这是 beta 通道的意义所在

## 7. 出问题怎么退

| 情况 | 动作 |
|---|---|
| PyPI 包有问题 | `pip` 无法撤回已发布的文件，用 **yank**：PyPI 项目页 → Manage → Releases → Yank（已 pin 的用户不受影响，但新安装不会选它） |
| npm 包有问题 | `npm deprecate uiu-agent@0.2.0-b1 "原因"`（比 unpublish 安全）；确需移除才 `npm unpublish`（24 小时内且无人依赖时） |
| 只是版本号写错 | 不要复用旧号：直接发 `0.2.0b2` |

## 8. 本次（0.2.0b1）的特别说明

- 这是**首个把审计清单全部落地**的版本；相对 `0.1.7` 的差别见 CHANGELOG。
- 依赖分层已完成：核心 8 个依赖、全新 venv 约 2 分钟装完（`0.1.7` 时代要 30 分钟以上）。
- 尚未验证：真 LLM 端到端（需 `UIU_E2E_LIVE=1` + 真 key）、Linux/macOS、
  npm 完整安装链在**干净机器**上的表现（本机受沙箱限制只验到安装器自身逻辑）。
