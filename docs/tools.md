# 工具参考

> 本文件由 `python scripts/gen_tools_doc.py` 从 `uiu.tools` 注册表生成，**请勿手改**。
> 重新生成：`python scripts/gen_tools_doc.py`；CI 用 `--check` 校验是否过期。

共 **123** 个内置工具，按定义模块分组。带 ⚠ 标记的工具**默认需要用户确认**；
此外 `shell_exec` 与文件读写会在调用时按语义/路径动态判定（见 audit §5.2/§5.3）。

## agent_tools (4)

### `agent_file_editor`

调用外部 Claude Code 或 Codex agent 来修改或审查指定文件。

参数：`file_path` string*、`prompt` string*、`agent` string、`cwd` string

### `delegate`

把编程任务委派给外部 agent CLI（Claude Code 或 Codex）非交互执行。适合大型/独立任务。

参数：`agent` string*、`task` string*、`cwd` string、`model` string、`timeout` integer

### `launch_agent_terminal`

自动启动独立可见的 cmd 命令行窗口，并在其中运行外部 agent（如 Claude Code 或 Codex），方便交互式修改文件和观察进度。

参数：`agent` string、`task` string、`cwd` string、`keep_open` boolean

### `list_agents`

列出本机已安装的外部 agent CLI（claude / codex）

参数：无参数

## app (2)

### `app_launch`

启动程序或打开文件/URL。如果窗口未运行，使用此工具启动它。

参数：`target` string*

### `app_open_or_focus`

打开任何软件：已启动的自动弹到最前面置顶激活，未启动的自动智能查找并启动然后置顶（支持别名如'微信','Chrome','记事本','Outlook','VSCode'等）。

参数：`app_name` string*

## askui_tools (2)

### `askui_autopilot`

用 AskUI 在桌面执行自然语言指令。通过 Computer Vision 操作任何桌面软件（微信、Office、记事本等）。例：'点击微信的文件传输助手'

参数：`instruction` string*

### `look`

截图分析当前屏幕状态。返回前台窗口、所有可见窗口、屏幕文字及坐标。每次操作前后调用以验证状态。

参数：`region` string

## autonomous (1)

### `autonomous_goal_run`

自主多轮任务执行器（类 Claude Code / Hermes 架构）：包含思考(Thought)、行动(Action)、观察(Observation)、反思(Reflection)四元自适应循环，并在完成后自动编译为宏记忆沉淀。

参数：`goal` string*、`max_steps` integer

## browser (9)

### `browser_cdp_action`

浏览器 CDP 混合自动化：若 Chrome/Edge 开启了调试端口 9222，直接执行 DOM CSS 点击、读取 innerText 或运行 JS。

参数：`action` string*、`selector` string

### `browser_compile_macro`

将探索成功的浏览器动作序列自动编译为独立、零延迟、带视觉自愈热修补能力的 Python Playwright 宏脚本并注册。

参数：`name` string*、`description` string、`start_url` string、`steps` array*、`parameters` array

### `browser_content_extract`

从已接管浏览器当前页面中高精度提取内容（支持 markdown 结构化正文、table 结构化表格、text 纯文本、html 节点代码），告别 OCR 模糊与换行错位。

参数：`mode` string、`selector` string、`max_chars` integer

### `browser_default_attach`

接管用户日常 Chrome/Edge/Brave 浏览器：免登录、保留全部 Cookie 与已打开标签页，通过 CDP 调试端点附着至当前活动页面。

参数：`port` integer、`browser` string、`auto_restart` boolean

### `browser_eval_js`

在已接管浏览器的活动页面上下文安全执行自定义 JavaScript 脚本并返回序列化结果。

参数：`script` string*

### `browser_explore_step`

在已接管的默认浏览器中执行探索性交互步进：支持 'inspect' 获取当前页可交互元素树；或执行 'click', 'fill', 'press', 'hover', 'scroll', 'navigate' 并自动提取复合指纹与效应核验。

参数：`action` string、`target` string、`value` string

### `browser_list_installed`

扫描当前系统上已安装的全部现代浏览器（Chrome, Edge, Brave等），返回可执行路径、配置目录、默认浏览器标识及当前运行状态。

参数：无参数

### `browser_macro_run`

零延迟直接运行已编译的 Playwright 浏览器宏（支持传入动态参数，如 keyword='Python'），内置前端改版视觉自愈与原地热修补。

参数：`name` string*、`kwargs` object

### `browser_tabs_manage`

管理已接管浏览器的标签页：列出所有标签页(list)、去重打开或激活网址(open)、切换到指定标题/网址的标签页(switch)、或关闭标签页(close)。

参数：`action` string*、`target` string、`url` string

## browser_login (2)

### `chrome_auto_login`

自动化操作 Chrome 浏览器执行账号密码登录，自动 OCR 截取识别图片验证码并点击提交登录。

参数：`url` string、`username` string*、`password` string*、`captcha` boolean、`submit_button` string、`max_retries` integer

### `solve_captcha_ocr`

截图并使用 OCR 智能识别屏幕上的图片验证码，支持字母数字验证码和加减乘除算术验证码自动计算。

参数：`region` array、`hint` string、`arithmetic` boolean

## browser_tools (6)

### `browser_click`

点击快照中的元素（按 [ref] 或可见文本）。

参数：`ref` string*

### `browser_fill`

在快照中的输入框填表（按 [ref] 或占位文本）。

参数：`ref` string*、`text` string*

### `browser_navigate`

受控浏览器跳到指定 URL（确定性，需 playwright；复杂自主任务改用 browser_use）。

参数：`url` string*

### `browser_open`

在默认浏览器打开网址（简单操作，不走 AI agent）。适合单纯打开网页。

参数：`url` string*

### `browser_snapshot`

当前页可交互元素快照（返回 role/name/[ref] 列表，给 click/fill 用；无 playwright 时提示降级 web_extract）。

参数：无参数

### `browser_use`

用 AI agent 在浏览器中自动执行任务。能点击、输入、填表、提取数据。例：'在百度搜索Python'、'查看GitHub仓库star数'

参数：`task` string*、`url` string

## check (1)

### `check_chatgpt_quota`

一键直达免思考查询 ChatGPT 客户端剩余额度与使用限制（全流程 1.5 秒内直接返回结果）。

参数：`scroll_for_more` boolean

## clarify (1)

### `clarify`

向用户反问澄清（会阻塞等回答）。需求不明、有多个合理走向、破坏性操作前确认时用。优先于瞎猜。

参数：`question` string*、`options` array

## clipboard (1)

### `clipboard_data_pipeline`

跨软件多模态剪贴板管道：支持纯文本、富图像(CF_DIB)、结构化表格(TSV/Markdown/CSV)的高速剪贴板读写与解析。

参数：`mode` string*、`text` string、`table_data` array、`format` string

## coordinate (1)

### `coordinate_anti_drift`

计算高精度抗漂移安全点击坐标，支持安全内边距、文本框输入优化、物理/逻辑DPI转换与归一化坐标转换。

参数：`box` array*、`strategy` string、`is_physical` boolean

## cron (3)

### `cron_add_job`

创建绝对定时或周期定时任务（支持绝对时间如 'once 2026-09-07T18:00:00'、每天固定时间 'daily 09:00'、间隔时间 '30m'/'2h'、5段cron表达式）。到点自动执行指定任务。

参数：`name` string*、`schedule` string*、`task` string*

### `cron_list_jobs`

列出当前工作区中所有配置的定时任务列表与下次触发时间。

参数：无参数

### `cron_remove_job`

删除指定的定时任务（支持传入任务 ID 或任务名称）。

参数：`job_id` string*

## delegation (2)

### `delegate_batch`

并行委派多个独立子任务（最多8个），按序返回各结论。

参数：`tasks` array*、`tools` array、`max_rounds` integer

### `delegate_task`

把子任务委派给内建子 agent（隔离上下文独立执行，适合独立可并行的子任务）。返回子 agent 的结论。

参数：`task` string*、`tools` array、`max_rounds` integer

## display (1)

### `display_scaling_info`

获取多显示器几何布局、系统/监视器DPI缩放比（100%, 125%, 150%, 200%）与坐标系校准报告。

参数：无参数

## email_gui (1)

### `send_email_via_gui`

通过屏幕 OCR 找字与鼠标键盘点击，在真实桌面邮件客户端（如 Outlook / Foxmail）中纯界面自动化撰写并发送邮件（免配置 SMTP 密码）。

参数：`client` string、`to` string*、`subject` string*、`body` string*、`cc` string

## file_tools (6)

### `cleanup_temp_screenshots`

清理运行和测试遗留的临时/调试截图文件，释放磁盘空间。

参数：`directory` string、`pattern` string、`max_age_seconds` integer

### `directory_list`

列出指定文件夹内的子文件和目录列表，包含文件大小。

参数：`path` string、`recursive` boolean、`max_depth` integer

### `file_copy`

复制文件或文件夹到指定目标位置。

参数：`src` string*、`dst` string*、`overwrite` boolean

### `file_delete`

删除指定文件。

参数：`path` string*

### `file_get_content`

获取文件内容，支持分行读取（start_line, end_line），避免大文件撑爆上下文。

参数：`path` string*、`start_line` integer、`end_line` integer、`max_chars` integer

### `file_move`

移动或重命名文件或文件夹。

参数：`src` string*、`dst` string*、`overwrite` boolean

## gui (1)

### `gui_action_pipeline`

极速免思考连续执行 GUI 复合动作流（每步控制在 0.5 秒内，规避多轮 LLM 思考与网络往返）。

参数：`steps` array*

## hierarchical (1)

### `hierarchical_execute`

基于 Microsoft UFO 架构的 HostAgent + AppAgent 双层分级协同调度器：将跨软件复杂长任务自动拆解为应用子任务，自动调度 App 专家执行并汇聚成果。

参数：`goal` string*

## ime_tools (2)

### `ensure_english_ime`

强制切到英文输入模式（按 Shift 或 Alt+Shift）。输入 ASCII 文字前必须先调用，防止中文输入法把字母变汉字（如 uiuagent → uiu阿根廷）。

参数：无参数

### `ime_state`

检查当前输入法状态（中文/英文、IME 开/关）。输入文字前应调用确保是英文模式，避免中文输入法把字母吃成汉字。

参数：无参数

## keyboard (1)

### `keyboard_shortcut`

按下单键或组合键（如确认用 ['enter']，快捷键用 ['ctrl', 'c']）。

参数：`keys` array*

## learning (7)

### `memory_add`

把值得长期记住的事实追加到记忆库（如用户偏好、项目背景、常用命令）。自动带时间戳。

参数：`content` string*

### `memory_recall`

读取已存储的长期记忆（关于用户、项目、偏好的事实）。

参数：无参数

### `memory_remove`

删除一条包含指定内容的记忆条目（先 memory_recall 找到原文再删）。

参数：`content` string*

### `memory_replace`

更新一条已有的记忆（先 memory_recall 找到原文）。

参数：`old` string*、`new` string*

### `record_verified_action`

当一次桌面 GUI 或系统操作真实生效并验证后，立即调用此工具将操作拆解沉淀为可复用技能与记忆（写入 SKILL.md 与 MEMORY.md）。

参数：`action_name` string*、`target_app` string*、`steps` array*、`verification` string*、`notes` string

### `skill_create`

把一次成功的问题解决方法沉淀成可复用技能（写入 SKILL.md）。当用户重复做类似的事、或你发现一个可复用流程时使用。

参数：`name` string*、`description` string*、`instructions` string*

### `skill_improve`

改进已有技能：追加一条使用记录或修订。当发现之前沉淀的方法有更优做法时使用。

参数：`name` string*、`note` string*

## macro (2)

### `macro_auto_compile`

基于自我编程演进范式：将动作步骤序列自动编译为原生高性能 Python 宏代码并注册，实现后续 0 思考毫秒级复用。

参数：`name` string*、`target_app` string、`steps` array*、`parameters` array

### `macro_fast_run`

从情境经验记忆库中召回或直接运行已编译的原生零延迟宏（全流程 < 1 秒，0 思考）。

参数：`macro_name` string*、`kwargs` object

## macros (6)

### `macro_detect_pattern`

分析已录制的宏，自动挖掘重复出现的动作序列，剥离多余的前置/后置动作，提取出纯净的最小单次循环宏。

参数：`name` string、`save_as` string

### `macro_list`

列出所有已保存的宏及步数、描述。

参数：无参数

### `macro_play` ⚠

回放一个已录制的宏（真实控制鼠标键盘）。执行前必须先向用户确认目标窗口已就绪；回放中甩鼠标到屏幕左上角或按 F9 可紧急中止。

参数：`name` string*、`speed` number、`start` integer、`end` integer

### `macro_record`

录制一段鼠标键盘操作存为宏（按 F9 结束录制）。录制时请用户先切到目标窗口再开始，录完可 macro_play 回放。适合把重复性 GUI 操作变成可复用宏。

参数：`name` string*、`description` string、`timeout` integer

### `macro_remove`

删除一个宏。

参数：`name` string*

### `quick_macro_listen`

启动或停止经典按键精灵全局热键监听模式。用户按下 F10 开始/结束录制，按 F12 毫秒级单次回放，Ctrl+F12 循环 10 次，F11 随时紧急刹车。当用户说'我要做重复操作/帮我记一下动作'时调用。

参数：`action` string

## memory_rag (4)

### `add_memory`

添加一条新记忆到 MEMORY.md 并索引到向量数据库。

参数：`text` string*、`title` string

### `auto_embed`

将 MEMORY.md 内容索引到向量数据库，支持语义搜索。首次使用或记忆更新时调用。

参数：`memory_text` string*

### `memory_state`

检查记忆系统状态（向量数据库、嵌入模型是否可用）

参数：无参数

### `recall_semantic`

语义搜索记忆。比关键词匹配更智能，能理解含义相近的查询。

参数：`query` string*、`n_results` integer

## monitor_tools (3)

### `check_notifications`

综合检测系统通知与消息（支持一键检查 Outlook 邮件、微信新消息）。

参数：`target` string

### `check_outlook_emails`

检测 Outlook 邮箱中的最新未读邮件，返回发件人、主题、接收时间和正文摘要。

参数：`unread_only` boolean、`limit` integer

### `check_wechat_messages`

检测桌面微信的新消息，自动识别未读红点联系人及当前聊天窗口的最新消息内容。

参数：`unread_only` boolean、`check_active_chat` boolean

## mouse (2)

### `mouse_click_at`

点击屏幕上的物理绝对坐标。配合 screen_ocr_find 找到的坐标使用。

参数：`x` integer*、`y` integer*、`button` string、`clicks` integer

### `mouse_scroll_at`

在指定位置滚动鼠标滚轮翻页。

参数：`clicks` integer*、`x` integer、`y` integer

## proc_tools (4)

### `list_procs`

列出后台任务。

参数：无参数

### `proc_kill` ⚠

终止后台任务。

参数：`pid` string*

### `proc_log`

读后台任务日志尾部。

参数：`pid` string*、`tail` integer

### `proc_run`

后台运行耗时命令（立即返回，不阻塞）。查日志用 proc_log，结束用 proc_kill。

参数：`command` string*、`cwd` string

## process (1)

### `process_health_check`

检测指定应用窗口是否处于未响应/假死状态（IsHungAppWindow），并返回 CPU、内存与健康诊断报告。

参数：`target` string*、`auto_revive` boolean

## read (2)

### `read_file`

Read a UTF-8 text file. Returns the content or an error message.

参数：`path` string*

### `read_spreadsheet`

读取 Excel (.xlsx) 文件内容，直接解析文件不走屏幕 OCR，准确。返回单元格数据表格。

参数：`path` string*、`max_rows` integer

## resilient (1)

### `resilient_click`

极高鲁棒性自愈点击：自动等待界面动画渲染沉降、自动检测并消解意外遮挡弹窗，并在未生效时触发自愈重试。

参数：`target` string*、`region` array、`wait_stable` boolean、`auto_dismiss_popups` boolean

## screen (2)

### `screen_icon_find`

定位屏幕上的纯图形图标（如铅笔、齿轮设置、删除、复制等无文字按钮），支持模板匹配与文字锚点相对推导。

参数：`icon_name` string、`anchor_text` string、`direction` string、`index` integer、`region` array

### `screen_ocr_find`

OCR 屏幕找字，返回目标文字在屏幕上的绝对物理中心坐标 (x, y)。

参数：`target_text` string*、`scroll_if_missing` boolean

## screen_tools (6)

### `click_in_region`

在指定区域内查找并点击文字（快速）。

参数：`text` string*、`region_x` integer*、`region_y` integer*、`region_w` integer*、`region_h` integer*

### `click_text`

点击屏幕上可见文字对应的按钮/元素。截图→OCR→找文字→点击。适合'点击提交/确定/登录按钮'这类命令。

参数：`text` string*、`click_count` integer

### `ocr_region`

OCR 识别屏幕指定区域的文字（快速，<0.5秒）。适合小范围识别。

参数：`x` integer*、`y` integer*、`w` integer*、`h` integer*

### `press_key`

按键或组合键，如 'enter'、'ctrl+s'、'alt+tab'。

参数：`keys` string*

### `screen_read_text`

读取整个屏幕的可见文字（OCR）。用户问'屏幕上有什么'或需要找元素时用。

参数：无参数

### `type_text`

在当前聚焦的输入框输入文字（先用 click_text 点击输入框聚焦）。

参数：`text` string*、`interval` number

## screen_watcher (2)

### `screen_watch_and_react`

高频截图巡检与监控（频率可控，如每秒1次），当满足目标文字出现/消失/视觉图像变动时，在1秒内极速触发响应或自动点击。

参数：`target_text` string、`condition` string、`region` array、`interval` number、`timeout` number、`action` string、`click_on_match` boolean

### `web_frequent_monitor`

对网页或软件窗口进行频繁截图监控，1秒内极速响应（例如抢单、监控特定数据更新、出现目标按钮立即点击）。

参数：`match_text` string*、`window_keyword` string、`interval` number、`timeout` number、`click_when_found` boolean

## scroll (1)

### `scroll_probe_find`

虚拟滚动探针：自动沿长页面/长列表滚动查找指定目标，通过画面差分自动探测滚动边界防止死循环。

参数：`target` string*、`anchor` string、`max_scrolls` integer、`scroll_clicks` integer

## sessions (1)

### `session_search`

在已保存的会话记录里做关键词检索（免费、秒回）。当用户说“我们上次聊过/之前说过 X”或你记不清是否处理过某主题时使用。返回命中片段及上下文。

参数：`query` string*、`limit` integer

## shell (1)

### `shell_exec`

Run a shell command and return its stdout/stderr. Use for quick inspection, git, scripts.

参数：`command` string*、`cwd` string

## skills_runtime (2)

### `skill_view`

按需读取一个 skill 的完整 SKILL.md 全文。

参数：`name` string*

### `skills_list`

列出 skill 索引（仅名字+一句话）。需要某个 skill 的完整用法时再 skill_view 取全文。

参数：无参数

## smart (1)

### `smart_interact`

统一多模态自愈交互原语：自动执行 UIA -> OCR -> 锚点图标 -> 模板匹配 四级降级重试，并核验点击前后屏幕视觉变化，杜绝静默失败。

参数：`target` string*、`action` string、`region` array、`verify_change` boolean、`window_title` string

## som (1)

### `som_click_tag`

通过 Set-of-Mark 编号标签直接交互：指定编号（如 1 或 '1'）直接执行自愈点击，杜绝误触与坐标偏移。

参数：`tag` string*、`action` string、`verify_change` boolean

## spatial (1)

### `spatial_anchor_find`

相对空间拓扑定位：基于锚点元素查找相对方位的目标控件（支持 'right', 'left', 'below', 'above', 'inside'）。例如：点击‘智谱 GLM’右侧的‘编辑’。

参数：`target` string*、`anchor` string*、`relation` string、`max_distance` number

## system_tools (9)

### `check_network`

检查网络连通性（ping）。用户说'网通不通'时用。

参数：`host` string

### `clipboard_get`

读取剪贴板内容。用户问'我复制了什么'时用。

参数：无参数

### `clipboard_set`

把文字写入剪贴板。

参数：`text` string*

### `get_time`

看当前时间/日期/星期。用户问'几点了/今天周几'时用，别用 shell 查时间。

参数：无参数

### `open_url`

在默认浏览器打开网址，或搜索（输入无网址的文本会搜索）。如'打开哔哩哔哩'、'搜索今天的新闻'。

参数：`url` string*

### `shutdown` ⚠

关机/重启/注销/睡眠。危险操作，必须先跟用户确认！

参数：`action` string*

### `software_inventory`

统计本机安装的系统软件、当前版本，并通过 winget 检查是否有最新版本及升级状态。

参数：`filter_keyword` string、`check_updates` boolean、`limit` integer

### `system_info`

查看系统信息：CPU/内存/磁盘/电池/开机时长。用户问'电脑卡不卡/内存多大/还有多少电'时用。

参数：无参数

### `take_screenshot`

截屏保存为图片（默认保存到桌面）。用户说'截个图'时用。

参数：`path` string

## task (1)

### `task_checkpoint_manage`

长任务检查点与 WAL 事务管理：查看未完成任务列表、断点续跑、或执行事务回滚。

参数：`action` string*、`task_id` string

## text (1)

### `text_paste`

通过剪贴板安全写入文本（防输入法拼音打偏）。

参数：`text` string*、`clear_before` boolean

## ui (1)

### `ui_control_find`

通过 Windows UIA 辅助功能树直接探测无文本控件（基于 aria-label、Name、AutomationId 等无障碍属性，<1ms 零视觉开销）。

参数：`name` string、`control_type` string、`window_title` string、`automation_id` string

## update (1)

### `update_cc_switch_provider_remark`

一键秒级免思考修改 CC Switch 中指定供应商的备注信息（带窗口恢复、悬浮交互与底层数据库核验）。

参数：`provider_name` string*、`new_remark` string*

## visual (1)

### `visual_tag_screen`

生成 Set-of-Mark 视口交互标记：为当前屏幕或区域内所有可交互控件与文本打上高对比度编号标签（[1], [2], [3]...），杜绝视觉模型坐标幻觉。

参数：`region` array、`window_title` string、`max_elements` integer

## voice_tools (3)

### `listen`

录制麦克风语音并转成文字。支持中文和英文。适合语音输入指令。

参数：`duration` integer、`language` string

### `speak`

把文字转换成语音朗读出来。支持中文和英文。适合汇报结果、朗读文章。

参数：`text` string*、`voice` string、`rate` integer、`save_path` string

### `voice_state`

检查语音功能可用状态（TTS/STT 哪些已安装）

参数：无参数

## wait (1)

### `wait_screen_stable`

等待屏幕或指定区域画面变动沉降静止（用于等待加载完成或过渡动画结束）。

参数：`region` array、`max_wait_ms` number

## web_tools (2)

### `web_extract`

抓取网页正文（自动去导航/广告标签）。读搜索结果、文档页面时用。

参数：`url` string*、`max_chars` integer

### `web_search`

联网搜索（DuckDuckGo，无需配置）。查资料/新闻/文档时用，返回标题+链接+摘要。

参数：`query` string*、`count` integer

## wechat_tools (1)

### `send_wechat` ⚠

微信专属 8 步语义闭环发消息工具：置顶→定位联系人→点击→核对标题→聚焦输入区→核对输入文字→回车发送→核对上屏。有严密校验防误发。

参数：`contact` string*、`message` string*

## window (3)

### `window_focus`

置顶并激活指定软件窗口。任何软件操作前必须先置顶。

参数：`title_keyword` string*

### `window_layout_tile`

智能视口与双屏吸附：将单/双应用窗口自动分屏并排吸附对齐（left/right/top/bottom/center），确保视觉 Agent 能同时观测并协同两个软件。

参数：`app1` string*、`app2` string、`position` string

### `window_list`

列出当前桌面所有打开的窗口（获取标题、位置等）。操作软件前建议先确认软件是否已打开。

参数：无参数

## write (1)

### `write_file`

Write UTF-8 text to a file (overwrites). Creates parent dirs.

参数：`path` string*、`content` string*
