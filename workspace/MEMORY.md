# MEMORY — 跨会话长期记忆

> agent 不会自动写这里。你自己在对话里输入 `/memory <内容>` 就能追加一行。
> 也可以手动编辑。记录那些"以后还会用到"的事实。

- 项目根目录：e:\Code\Personal\agent\my-agent
- [2026-09-07] CC Switch 架构与UI规律：窗口标题 'CC Switch'，进程 'cc-switch.exe' (Tauri)。若处于最小化状态必须先 win32gui.ShowWindow(hwnd, win32con.SW_RESTORE) 再激活。
- [2026-09-07] CC Switch 卡片操作规律：卡片纵向排布 (间距 98px，首项约 y=237)；右侧操作按钮平时隐藏，鼠标移至卡片区域 (x=win_left+500, y=card_cy) 悬浮触发；[编辑(铅笔)] 图标位于蓝色启用按钮右侧 +22px 处。
- [2026-09-07] CC Switch 弹窗与数据库：编辑弹窗中备注输入框相对坐标 (win_left+296, win_top+389)，保存按钮相对坐标 (win_left+670, win_top+828)。底层 SQLite 数据库位于 'C:\Users\haibao.feng\.cc-switch\cc-switch.db'，表 'providers' 字段 'notes'。
