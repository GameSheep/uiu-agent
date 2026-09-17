# 平台支持矩阵

> 结论先说：**Windows 是一等公民**，Linux / macOS 只能跑「核心能力」——
> CLI、TUI、网关、会话/记忆/技能、联网工具可用；桌面自动化、屏幕 OCR、微信闭环、
> 输入法、宏录制这些**不可用**。原因不是没写适配层，而是它们直接建立在 Win32 API 上。

## 能力矩阵

| 能力 | Windows | Linux | macOS | 说明 |
|---|---|---|---|---|
| CLI（init/show/config/model/skills/channel/cron/sessions/…） | ✅ | ✅ | ✅ | 纯 Python |
| 全屏 TUI（Textual） | ✅ | 未实测 | 未实测 | `app/` 无 win32 依赖 |
| 网关 `uiu serve`（HTTP + 渠道） | ✅ | 未实测 | 未实测 | `http.server` + 各渠道 SDK |
| 会话 / 记忆 / 技能 / 定时任务 | ✅ | ✅ | ✅ | 状态文件走 `_atomic`（msvcrt/fcntl 双实现） |
| 工具：文件 / shell / 联网 | ✅ | ✅ | ✅ | 纯 Python |
| 剪贴板 | ✅ | 部分 | 部分 | 优先 pyperclip，Windows 另有 PowerShell 兜底 |
| 浏览器接管（CDP） | ✅ | ❌ | 部分 | Chrome/Edge/Brave 探测区分 win32/darwin |
| 桌面控制（窗口/点击/热键） | ✅ | ❌ | ❌ | `win32gui/win32api/pyautogui` |
| 屏幕 OCR / 图标定位 | ✅ | ❌ | ❌ | `screen-ocr[winrt]` + pyautogui 截图 |
| 微信自动化闭环 | ✅ | ❌ | ❌ | 依赖窗口管理 + OCR |
| 输入法（IME） | ✅ | ❌ | ❌ | `imm32` 系列 ctypes 调用 |
| 宏录制 / 回放 / 快速宏 | ✅ | ❌ | ❌ | 全局热键走 Win32 钩子 |
| 后台守护 `uiu daemon` + 开机自启 | ✅ | 部分（`daemon run` 可跑） | 部分 | 零窗口启动与 Startup 自启是 Windows 专有 |

「未实测」= 代码看起来跨平台，但**没有在 CI/真机上验证过**，不要当作承诺。

## 依赖 Windows 专有的模块

<!-- windows-only:begin -->
共 **30** 个模块直接依赖 Windows 专有库/接口：

- `_atomic.py` — msvcrt
- `askui_tools.py` — pyautogui, win32gui
- `auto_recovery.py` — pyautogui, uiautomation
- `browser_login.py` — pyautogui
- `daemon.py` — ctypes
- `data_pipeline.py` — win32clipboard, win32con
- `desktop_guard.py` — ctypes
- `desktop_tools.py` — win32api
- `dpi_manager.py` — ctypes, ctypes.wintypes, pyautogui, win32api
- `fast_pipeline.py` — pyautogui, win32con, win32gui
- `gui_primitives.py` — ctypes, pyautogui, win32clipboard, win32con
- `hierarchical_agent.py` — win32con, win32gui
- `icon_locator.py` — pyautogui
- `ime_controller.py` — ctypes
- `ime_tools.py` — ctypes, ctypes.wintypes, pyautogui
- `layout_manager.py` — ctypes, ctypes.wintypes, win32con, win32gui
- `macro_player.py` — ctypes
- `macro_recorder.py` — ctypes
- `monitor_tools.py` — pythoncom, win32com, win32gui
- `process_watchdog.py` — ctypes, win32gui, win32process
- `quick_macro.py` — ctypes
- `safe_update.py` — ctypes
- `safety_hud.py` — ctypes
- `screen_tools.py` — pyautogui, screen_ocr
- `screen_watcher.py` — pyautogui
- `system_tools.py` — pyautogui
- `uia_locator.py` — uiautomation
- `vision_locator.py` — pyautogui, win32gui
- `wechat_tools.py` — ctypes, pyautogui, win32api, win32con, win32gui, win32process
- `window_manager.py` — ctypes, win32api, win32con, win32gui, win32process, win32service
<!-- windows-only:end -->

## 非 Windows 上的行为

- 相关工具**仍然注册**（模型能看到 schema），调用时函数内部 `if sys.platform != "win32": return ...`
  提前返回错误或空结果——不会崩，但也别指望能用；
- `uiu doctor` 会给出 `platform/degraded` 提示（非 Windows 上列出不可用能力）；
- 可选 extras 带平台标记：`uiautomation` / `screen-ocr[winrt]` / `pywin32` 只在 `sys_platform == 'win32'` 下安装。

## CI

CI 只跑 **windows-latest**（`.github/workflows/ci.yml`），这与「Windows 一等公民」的定位一致；
Linux/macOS 目前没有流水线，因此任何「跨平台可用」的说法都属于**未验证**。
