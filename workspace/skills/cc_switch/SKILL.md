---
name: cc_switch
description: CC Switch 供应商配置与备注修改技能，支持 UI 悬浮触控与底层 SQLite 双通道秒级操作。
---

# CC Switch 自动化操作指南

## 何时使用
当用户需要：
1. 修改 CC Switch 中某个模型供应商的备注或配置（如 "把 Zhipu GLM 备注改为 xxx"）。
2. 切换当前生效的供应商。
3. 查询或核对 CC Switch 当前配置状态。

## 系统特征与架构
- **进程名**：`cc-switch.exe`（基于 Tauri 框架构建的跨平台桌面应用）。
- **主窗口标题**：`CC Switch`。
- **本地数据库**：`C:\Users\haibao.feng\.cc-switch\cc-switch.db`（SQLite 格式），核心表为 `providers`，备注字段为 `notes`。

---

## 5 步拆解标准化执行流 (GUI SOP)

### 步骤 1：前台唤醒与最小化恢复 (Window Restore & Focus)
- 若窗口未打开，执行 `app_launch("CC Switch")`。
- 若窗口处于最小化（Windows 任务栏状态），普通 `focus_window` 无法正常渲染绘制，**必须先执行恢复调用**：
  ```python
  import win32gui, win32con
  win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
  focus_window(hwnd)
  ```
- 等待 150ms 确保窗口绘制完成，获取窗口矩形 `(win_left, win_top, win_right, win_bottom)`。

### 步骤 2：卡片悬浮与动作激活 (Hover Activation)
- 供应商列表垂直排列，行中心坐标公式：
  `card_cy = win_top + 237 + index * 98`（首项约 index=0，依次递增）。
- **关键机制**：卡片右侧的快捷操作按钮（[> 启用]、[编辑]、[复制]、[延迟] 等）在默认状态下是**完全隐藏**的。
- 必须先将鼠标移动到卡片区域内产生悬浮（Hover）：
  `mouse_move_to(win_left + 500, card_cy)`
- 悬浮后，右侧动作栏瞬间显现。

### 步骤 3：编辑图标定位与点击 (Pencil Icon Click)
- 悬浮激活后，右侧先出现蓝色主按钮（`[> 启用]` 或 `[正在使用]`）。
- 编辑按钮（铅笔图标）固定位于蓝色按钮右边缘旁：
  `pencil_x = blue_button_right + 22px`，`pencil_y = card_cy`（实测典型屏幕坐标 `x=934, y=549`）。
- 执行瞬时点击：`mouse_click(pencil_x, pencil_y)`。

### 步骤 4：弹窗表单交互与中英粘贴 (Modal Form Input)
- 点击后弹出居中的 "编辑供应商" 模态框。
- 备注输入框定位：
  - 视觉定位："备注" 文本输入框。
  - 相对坐标基准：`(win_left + 296, win_top + 389)`。
- 点击输入框并全选清空（`Ctrl+A -> Backspace`）。
- **中英安全输入**：严禁逐字单键模拟（防中文输入法吃字母或打偏），一律通过剪贴板安全注入（`paste_text(new_remark)`）。
- 保存按钮定位：
  - 相对坐标基准：`(win_left + 670, win_top + 828)`。
  - 点击 "保存"。

### 步骤 5：双重闭环核验 (Dual Verification)
1. **界面 UI 提取**：在供应商卡片副标题区域提取文本，确认显示新备注。
2. **底层数据库核验**：
   ```python
   import sqlite3
   conn = sqlite3.connect(r"C:\Users\haibao.feng\.cc-switch\cc-switch.db")
   cur = conn.cursor()
   cur.execute("SELECT id, name, notes FROM providers WHERE name LIKE ?", (f"%{provider_name}%",))
   row = cur.fetchone()
   assert row[2] == new_remark
   ```

---

## 极速通道 (Sub-Second Fast Pipeline)
未来再次执行此类任务时，无需任何中间大模型反思，直接调用内建专用流水线：
- Python 工具：`update_cc_switch_provider_remark(provider_name, new_remark)`
- 耗时：全流程 < 1.0 秒。
