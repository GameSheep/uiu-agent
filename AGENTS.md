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
- 覆盖率（需先 `pip install -e ".[test]"`，CI 会跑并卡门槛）：
  `.venv\Scripts\python.exe -m pytest tests -q --cov=uiu --cov-report=term-missing --cov-fail-under=50`
  基线 50（2026-09-17 实测 53.5%）。只保证不回退；新增代码请自带测试，阈值随轮次抬高。
- 界面预览：`.venv\Scripts\python.exe scripts/tui_preview.py`（11 个状态 → `docs/preview/`）；
  界面导览见 `docs/tui-tour.md`。

## 已知环境限制
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
- 测试不要依赖墙上时间：需要「回合进行中」就先断言 `app._turn_running`，并把假回合的 sleep 放长；
  需要断言「本次反馈」就先清掉上一条 toast。慢机器上 0.9s 的回合会在两行断言之间就结束。

## 提交前自检（一次过）
1. `.venv\Scripts\python.exe -m compileall -q src/uiu scripts`
2. `.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider`（**全量**，不要只跑改动文件——
   竞态/时序问题只在全量负载下暴露）
3. `.venv\Scripts\python.exe cli_smoke.py`
4. 改了界面：`.venv\Scripts\python.exe scripts/tui_preview.py` 重新生成 `docs/preview/`
5. 推送前先 `git ls-remote origin` 探连通性（沙箱里 SSH 会失败，别等到最后才发现）
