"""clarify — agent 向用户反问澄清（Hermes clarify 工具最小版）。

机制：模块级 ask handler，由宿主注入：
- TUI：同步 console 提问（input）
- 网关：发送问题到聊天并阻塞等下一条消息（带超时）
- 未注入时：返回指导文本，模型改用纯文本提问（不崩）
"""

from __future__ import annotations

_ask = None  # ask handler: fn(question, options|None) -> str


def set_ask_handler(fn) -> None:
    global _ask
    _ask = fn


def get_ask_handler():
    """Current ask handler (None when no UI is attached)."""
    return _ask


def clarify(question: str, options: list[str] | None = None) -> str:
    """Ask the user a clarifying question and wait for the answer."""
    question = (question or "").strip()
    if not question:
        return "[error] question 不能为空"
    if len(question) > 2000:
        return "[error] question 过长"
    opts = None
    if options:
        opts = [str(o)[:200] for o in options[:10]]
    if _ask is None:
        hint = "（clarify 通道未接入宿主——请直接在回复里向用户提问）"
        if opts:
            hint += " 选项：" + " / ".join(opts)
        return f"{question}\n{hint}"
    try:
        return _ask(question, opts) or "(用户未回答)"
    except Exception as e:
        return f"[error] 提问失败: {type(e).__name__}: {e}"


CLARIFY_DEF = {
    "type": "function",
    "function": {
        "name": "clarify",
        "description": "向用户反问澄清（会阻塞等回答）。需求不明、有多个合理走向、破坏性操作前确认时用。优先于瞎猜。",
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "要问的问题"},
                "options": {"type": "array", "items": {"type": "string"},
                            "description": "候选项（可选，最多10个）"},
            },
            "required": ["question"],
        },
    },
}

CLARIFY_TOOLS: dict[str, dict] = {
    "clarify": {"def": CLARIFY_DEF, "fn": clarify},
}


def clarify_tool_defs() -> list[dict]:
    return [t["def"] for t in CLARIFY_TOOLS.values()]
