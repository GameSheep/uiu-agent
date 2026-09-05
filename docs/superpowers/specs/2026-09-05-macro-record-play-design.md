# 设计：uiu 宏录制回放（按键精灵式 GUI 自动化）

日期：2026-09-05 · 状态：已确认

## 背景与目标

uiu 已具备完整 GUI 原子操作（`gui_primitives.py`：点击/拖拽/滚轮/按键/粘贴，pyautogui + win32）。
用户希望获得「按键精灵式」能力：**录制一段鼠标键盘操作，之后自动重放**，用于软件/网页/游戏中的重复性劳动。

对比 Hermes/OpenClaw，这是一项独特差异化能力：两大主流 agent 都只做「AI 看屏幕后单步操作」，
没有「录一段人工操作 → 原样回放」的闭环。而 AI 还能直接读写宏文件（JSON 文本），
所以**宏可录制、可回放、更可由 AI 生成/编辑**——这是把 AI 变成「自动化脚本作者」的关键。

## 核心原则（用户约束）

- **极致精简**：零新依赖（只用现有 pyautogui + win32），代码量最小
- **复用而非重造**：回放执行直接调用现有 `gui_primitives` 原语，不发明新引擎
- **稳定安全**：录制可热键停止、回放前确认、回放中可中止、宏文件纯文本可审查
- **只记关键操作**：不记录鼠标扫过的轨迹（慢且不准），只记点击/按键/输入/滚轮/等待

## 存储格式

位置：`workspace/macros/<name>.json`

```json
{
  "name": "export_report",
  "description": "打开报表系统并导出",
  "created": 1788600000,
  "steps": [
    {"t": "click", "x": 320, "y": 480, "button": "left", "clicks": 1, "delay_before": 1.2},
    {"t": "type", "text": "admin", "delay_before": 0.3},
    {"t": "key", "key": "enter", "delay_before": 0.2},
    {"t": "wait", "sec": 2.5},
    {"t": "scroll", "clicks": -3, "x": 100, "y": 200, "delay_before": 0.1},
    {"t": "hotkey", "keys": ["ctrl", "s"], "delay_before": 0.5}
  ]
}
```

- `delay_before`：距上一步真实间隔（录制捕获，回放保时序），单位秒，保留 2 位小数
- 步骤类型：`click` `type` `key` `wait` `scroll` `hotkey`（拖拽 `drag` 可选扩展，首版不做）
- **无鼠标移动轨迹**：鼠标移动本身不产生步骤，只有点击/滚轮才落点

## 架构与组件

### 1. `src/uiu/macro_recorder.py`（录制引擎，~120 行）

轮询式全局监听线程（零依赖，无 pynput）：

- 每 ~15ms 采样：
  - 鼠标：`pyautogui.position()` 变化 + 检测点击——通过 win32 `GetAsyncKeyState(VK_LBUTTON/RBUTTON/MBUTTON)` 的**按下沿**（先前未按→现在按下）判定一次 click
  - 键盘：`GetAsyncKeyState` 扫一组常用键的按下沿；**特殊字符/文本不逐键录**，避免把输入法组合录成乱码
- 用户输入文本：无法从全局钩子可靠还原（有 IME 组合）——录制 UI 提供「在需要输入处按 **F2 插入一段文本输入步骤**」的方式：弹输入框填文本 → 录成 `{"t":"type"}`。**这是关键设计**：录制时人工插入文本步骤，而不是录键盘逐键。
- 停止：默认 F9 热键停止；也支持超时自动停（如 `--timeout 300`）
- 事件带时间戳 → 算 `delay_before`

对外 API：
```python
def record_macro(path: Path, stop_key: str = "F9", timeout: int = 0) -> dict:
    """阻塞录制直到热键/超时。返回 {"steps": [...], "aborted": bool}"""
def _sample_once() -> list[dict]:   # 单次采样（可测试）
```

### 2. `src/uiu/macro_player.py`（回放引擎，~100 行）

- 逐条执行步骤，每条前先 sleep `delay_before / speed`
- 每条调用 `gui_primitives` 对应函数（click → `mouse_click`，key/hotkey → `press_key/press_hotkey`，scroll → `mouse_scroll`，type → `paste_text`，wait → sleep）
- `speed`: 回放速度倍率（默认 1.0；2.0 快一倍）
- **中止**：pyautogui FAILSAFE 已内置（鼠标甩到屏幕左上角即抛异常中断）；另监听 F9 软中止（与录制同键，心智一致；回放宏本身含 F9 步骤时除外——中止键检查先于步骤执行，步骤为 F9 时不中止）
- 每步前检查 `stop_flag`（线程事件），供 UI/agent 中止
- 支持只回放部分（`--from/--to` 步数区间，调试用，可选）

对外 API：
```python
def play_macro(path: Path, speed: float = 1.0, stop_flag=None) -> tuple[int, str]:
    """逐条执行，返回 (执行步数, 状态/错误)。失败即停（默认），可配 continue_on_error"""
```

### 3. `src/uiu/macros.py`（工具注册，~100 行）

4 个 built-in 工具，注册进 `tools.py`：

| 工具 | 参数 | 行为 |
|---|---|---|
| `macro_record` | name, description?, stop_key?, timeout? | 阻塞录制到热键，存 `workspace/macros/<name>.json` |
| `macro_play` | name, speed? | 回放（工具描述强制「先与用户确认目标窗口已就绪」） |
| `macro_list` | — | 列出已存宏 + 步数 + 描述 |
| `macro_remove` | name | 删除宏 |

### 4. CLI `uiu macro`（commands.py + main.py，~50 行）

```
uiu macro record <name> [--desc ...] [--timeout 300]   # F9 停止
uiu macro play   <name> [--speed 2] [--from N] [--to M]
uiu macro list
uiu macro remove <name>
```

## 数据流

```
[人工操作] --轮询钩子--> recorder --> workspace/macros/x.json
                                      │
[AI write_file 生成/编辑] ────────────┤  (宏是 JSON 文本 = AI 可写)
                                      ▼
                              player --gui_primitives--> 真实鼠标键盘
```

## 安全设计

1. **录制**：F9 热键停止；`--timeout` 自动停止兜底；录制不执行任何操作（只监听）
2. **回放前确认**：工具描述与 CLI 均要求确认目标窗口就绪（agent 工具由 agent 先问用户；CLI 回放前 `y/N` 提示，`--yes` 跳过）
3. **回放中**：pyautogui FAILSAFE（鼠标甩左上角立即中断）已内置；F9 软中止；每步前查 stop_flag
4. **宏文件可审查**：纯 JSON 文本落在 workspace，用户可读可改
5. **宏数量与大小**：单文件 ≤512KB（复用 `_sandbox` 写上限）；无自动执行定时器（宏不会自己跑，永远显式触发）

## 测试策略（零 GUI 环境可测）

- **录制**：单测 `_sample_once` 的点击/按键沿检测逻辑（mock win32 状态）；`record_macro` 用假 stop 事件验证循环与 steps 累积
- **回放**：mock `gui_primitives` 各函数，验证步骤顺序、delay_before 时序、speed 倍率、stop_flag 中止、失败即停
- **宏文件**：读写 roundtrip、非法 JSON 报错、`macro_list` 过滤非宏文件
- **CLI**：`uiu macro` 各子命令 smoke（list/remove 离线，record/play 走 mock）
- 注册表：4 工具进 `BUILTIN_TOOLS` + `tool_groups` 覆盖（延续 test_tools_registry 红线）

## 不做的事（YAGNI）

- ❌ 不记录鼠标移动轨迹（拖拽/画画场景以后用 `drag` 步骤类型扩展）
- ❌ 不逐键录文本输入（IME 不可靠）——用 F2 插文本步骤替代
- ❌ 不装 pynput（轮询够用且零依赖）
- ❌ 不做宏条件/循环/变量（那是完整 RPA 语言，违背精简）——需要时 AI 生成多段宏组合即可
- ❌ 不做宏定时自动触发（安全）
- ❌ 不做多屏/DPI 复杂处理（沿用 pyautogui 现状）
- ❌ 录制时不做窗口标题锚定（坐标是绝对物理坐标；AI 生成宏时可结合 OCR 做成相对定位的高级玩法，首版不做）
