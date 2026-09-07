"""Thread-safe bridge so the agent worker can ask the user (clarify/confirm).

run_turn runs on a worker thread and calls the clarify tool synchronously.
We hand the UI a handler that: posts an AskUser message to the event loop,
then blocks the worker thread on a threading.Event until the UI answers.
Timeout: if the UI never answers (e.g. app closing) we unblock with a default.
"""

from __future__ import annotations

import threading
from typing import Any, Callable

from textual.message import Message


class AskUser(Message):
    """Posted to the app: show a modal asking question with options."""

    def __init__(self, question: str, options: list[str] | None) -> None:
        super().__init__()
        self.question = question
        self.options = options or []


class ClarifyBridge:
    """Bound to the app; installed as the clarify ask handler."""

    def __init__(self, post: Callable[[Any], None], timeout: float = 600.0) -> None:
        self._post = post
        self._timeout = timeout
        self._lock = threading.Lock()
        self._waiter: threading.Event | None = None
        self._answer: str = ""

    def ask_sync(self, question: str, options: list[str] | None) -> str:
        """Called from the agent worker thread (blocking). Returns the answer."""
        ev = threading.Event()
        with self._lock:
            self._waiter = ev
            self._answer = ""
        try:
            self._post(AskUser(question, options))
        except Exception:
            with self._lock:
                self._waiter = None
            return ""
        ev.wait(self._timeout)
        with self._lock:
            ans = self._answer
            self._waiter = None
        return ans

    def answer(self, text: str) -> None:
        """Called from the UI thread when the user answers."""
        with self._lock:
            if self._waiter is not None:
                self._answer = text or ""
                self._waiter.set()
