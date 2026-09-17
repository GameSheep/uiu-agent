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

## Common Workflows
- 跑测试：`.venv\Scripts\python.exe -m pytest tests -q`（`tests/conftest.py` 会自动处理本机
  `mkdir(mode=0o700)` 生成拒绝访问目录的问题，无需自定义 runner）。
- 冒烟：`.venv\Scripts\python.exe cli_smoke.py`（自带临时目录回退）。
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
- 测试不要依赖墙上时间：需要「回合进行中」就先断言 `app._turn_running`，并把假回合的 sleep 放长；
  需要断言「本次反馈」就先清掉上一条 toast。慢机器上 0.9s 的回合会在两行断言之间就结束。

## 提交前自检（一次过）
1. `.venv\Scripts\python.exe -m compileall -q src/uiu scripts`
2. `.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider`（**全量**，不要只跑改动文件——
   竞态/时序问题只在全量负载下暴露）
3. `.venv\Scripts\python.exe cli_smoke.py`
4. 改了界面：`.venv\Scripts\python.exe scripts/tui_preview.py` 重新生成 `docs/preview/`
5. 推送前先 `git ls-remote origin` 探连通性（沙箱里 SSH 会失败，别等到最后才发现）
