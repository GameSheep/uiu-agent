# Memory

## Project Overview
See @README.md for project overview and @package.json for available npm/pnpm commands for this project.

## Code Style Guidelines
- Use descriptive variable names
- Follow existing patterns in the codebase
- Extract complex conditions into meaningful boolean variables

## Architecture Notes
- TUI：Textual。设计令牌集中在 `src/uiu/app/theme.py`（4 套内置主题 + `tui.colors` 覆盖），
  样式一律用令牌（`$accent` 等），不要写死颜色。注意 `$boost` 在本项目等价于透明，用 `$panel-lighten-*`。
- 长会话：`ChatView` 只常驻最近 60 条，更早的折叠 + 按页加载（上限 400）；
  滚到顶自动补页依赖「用户上滚」标记，**程序化滚动不得触发**。
- `src/uiu/app/widgets/*` 里覆写 Textual 的 watcher/生命周期方法时，若基类有同名实现**必须调 `super()`**
  （`watch_scroll_y` 漏调会同时弄坏滚动条位置、锚点和重绘）。

- 状态文件（sessions/config/cron/MEMORY.md/建议/情景记忆）**一律用 `uiu._atomic`**：
  `atomic_write_json/text` 落盘、`locked_update_json` 做读-改-写、`load_json_tolerant` 读损坏文件
  （会备份成 `.corrupt-<ts>` 再当空处理）。TUI / gateway / daemon 会同时写同一 workspace，
  裸 `write_text` 会丢更新或写坏文件。`file_lock` 是「进程内 RLock + 跨进程 OS 锁」两层，
  缺一不可（Windows 字节锁在同进程的不同句柄之间不冲突）。

## Common Workflows
- 跑测试：`.venv\Scripts\python.exe -m pytest tests -q`（`tests/conftest.py` 会自动处理本机
  `mkdir(mode=0o700)` 生成拒绝访问目录的问题，无需自定义 runner）。
- 冒烟：`.venv\Scripts\python.exe cli_smoke.py`（自带临时目录回退）。
- **CLI 代码分布**：`commands.py` 只是门面（再导出），实现按域拆在 `cli_shared.py`（通用工具）/
  `cli_basic.py`（init·show·version·audit·backup·restore·trash）/ `cli_model.py`（model·config·plugins）/
  `cli_channels.py` / `cli_skills.py` / `cli_sessions.py`（sessions·macro·quick）/
  `cli_automation.py`（cron·daemon）/ `cli_ops.py`（doctor·update·publish·serve）。加命令请放到对应域，
  并保持门面再导出（`from uiu.commands import cmd_x` 不能断）。
- 覆盖率（需先 `pip install -e ".[test]"`，CI 会跑并卡门槛）：
  `.venv\Scripts\python.exe -m pytest tests -q --cov=uiu --cov-report=term-missing --cov-fail-under=58`
  基线 58（2026-09-18 用真 coverage.py 实测 **60.2%**）。只保证不回退；新增代码请自带测试。
  当前零覆盖仅剩 `skill_installer.py`、`safe_update.py` 两个文件。
- 真 LLM 端到端（**默认跳过**，会真实花钱）：设 `UIU_E2E_LIVE=1` 后
  `.venv\Scripts\python.exe -m pytest tests/test_e2e_live_llm.py -q -m live`；
  验证的是「模型→工具→守卫→审计」整条链路，没有 key 或没开开关都会 skip。
- 界面预览：`.venv\Scripts\python.exe scripts/tui_preview.py`（11 个状态 → `docs/preview/`）；
  界面导览见 `docs/tui-tour.md`。

## 已知环境限制
- **pip / 一切 `mkdtemp` 工具在这台机器上会失败**（`mkdir(mode=0o700)` 被落成 deny ACL）。
  解法：`$env:PYTHONPATH="<repo>\.shim"` 后再跑（`.shim/sitecustomize.py` 把 mode 归一化成 0o777），
  并把 `TEMP/TMP` 指到普通目录（如 `<repo>\.piptmp`）。装包时再用国内镜像：
  `-i https://pypi.tuna.tsinghua.edu.cn/simple`。**这是环境 workaround，不是产品代码。**
- **`mkdir(mode=0o700)` 会生成自己都写不进去的目录**（本机 Windows + 沙箱把 mode 落成 deny ACL，
  `icacls` 都读不了）。pytest 的 tmp_path、`tempfile.mkdtemp` 都踩这个坑；`tests/conftest.py`
  与 `cli_smoke.py` 已各自兜底。若残留不可读目录（`.pytest_tmp/`、`mm_700/`、`tmp_pytest/`），
  需管理员权限删除。
- **沙箱内 `git push` 不可用**：`ssh.exe` 无法创建信号管道（Win32 error 5）。
  提交在本地照常，推送请在普通终端执行 `git push origin master`。

## 写代码时容易踩的坑（都被真实 bug 教育过）
- 不要写「数量 == N」这类会腐烂的断言（`cli_smoke.py` 曾钉死内置工具数=68，早已过时）。
- 气泡/行是**先挂载后填内容**的：依赖内容的可见性判断（比如有没有复制按钮）必须在挂载时就成立。
- 「空」只能有一个定义（`_turns()`），别用 markdown 文本长度之类间接信号。
- 面向用户的「能点/能按」必须真的有效：折叠条到上限就别再写「点击展开」，不可中断的命令别写 Esc。
- 静默丢弃用户操作是最糟的反馈：宁可弹一条红色轻提示说明原因。
- 测试里调用 `uiu.main.main()` 时，**不要让该 workspace 的 `.env` 含真实密钥名**
  （`main()` 会把 `.env` 载入 `os.environ`，会污染同进程后续测试 —— doctor 的 no-api-key
  检查曾因此误判）。用 `SMOKE_TOKEN=...` 这类中性名字。
- **用户可见输出要按「字节」想，不是按「文本」想**：中文 Windows 控制台是 GBK，
  `✓`/`✗`/`⚠` 这类符号不在码表里，`print()` 会抛 `UnicodeEncodeError` 把整条命令打挂
  （`uiu publish` 曾 4 秒就死）。CLI 输出统一走 `cli_io` 的 `_safe_print`，标记只用 ASCII
  （`[ok]`/`[x]`）。**这类问题用 `capsys` 测不出来**（它捕的是文本），
  必须起子进程 + `PYTHONIOENCODING=gbk` 才看得见。
- **不要在跑全量测试的同时改源码**：pytest 边收集边导入，改到一半的文件会被读到，
  产生假失败（我就这么污染过一次覆盖率统计）。先跑完、再改、再跑。
- 从 git 历史重新生成文件（如按域拆分）时要留意：**未提交的改动会丢**。本轮把 `commands.py`
  按域拆分时就用了 `git show HEAD:`，结果把还没提交的路径统一改动冲掉了。
- 测试不要依赖墙上时间：需要「回合进行中」就先断言 `app._turn_running`，并把假回合的 sleep 放长；
  需要断言「本次反馈」就先清掉上一条 toast。慢机器上 0.9s 的回合会在两行断言之间就结束。

## 提交前自检（一次过）
1. `.venv\Scripts\python.exe -m compileall -q src/uiu scripts`
2. `.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider`（**全量**，不要只跑改动文件——
   竞态/时序问题只在全量负载下暴露）
3. `.venv\Scripts\python.exe cli_smoke.py`
4. 改了界面：`.venv\Scripts\python.exe scripts/tui_preview.py` 重新生成 `docs/preview/`
5. 推送前先 `git ls-remote origin` 探连通性（沙箱里 SSH 会失败，别等到最后才发现）
