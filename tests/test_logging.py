"""Logging contract (audit P0-6 / §2.2).

长期驻留进程（gateway / daemon / cron）必须留下可回溯的日志：分级、轮转、落盘到
workspace，并且不能把密钥写进去。这里把这几条钉死。
"""

from __future__ import annotations

import importlib
import json
import logging
import threading
from pathlib import Path

import pytest

from uiu import log as L


@pytest.fixture(autouse=True)
def _clean_logging():
    L.reset_for_tests()
    yield
    L.reset_for_tests()


def _flush():
    for handler in L.get_logger().handlers:
        handler.flush()


def _text(ws: Path) -> str:
    _flush()
    target = L.log_path(ws)
    return target.read_text(encoding="utf-8") if target.exists() else ""


def test_setup_creates_rotating_log_file(tmp_path):
    ws = tmp_path / "ws"
    L.setup_logging(ws)
    L.get_logger("unit").info("hello %s", "world")
    body = _text(ws)

    assert "hello world" in body
    assert "[uiu.unit]" in body
    assert "INFO" in body
    # 轮转参数必须真的配上（曾经是手写 append，永不轮转）
    handler = next(h for h in L.get_logger().handlers
                   if isinstance(h, logging.handlers.RotatingFileHandler))
    assert handler.maxBytes > 0 and handler.backupCount >= 1


def _our_file_handlers(ws: Path) -> list[logging.Handler]:
    """我们自己的文件 handler（pytest 也会往 logger 上挂捕获 handler，不能直接数总数）。"""
    want = {str(L.log_path(ws))}
    out = []
    for handler in L.get_logger().handlers:
        name = getattr(handler, "baseFilename", None)
        if name and str(name) in want:
            out.append(handler)
    return out


def test_setup_is_idempotent(tmp_path):
    ws = tmp_path / "ws"
    for _ in range(3):
        L.setup_logging(ws)
    L.get_logger("unit").info("once")
    body = _text(ws)
    assert body.count("once") == 1, "重复 setup 不能叠加 handler"
    assert len(_our_file_handlers(ws)) == 1, "同一个日志文件只能挂一个 handler"


def test_level_comes_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("UIU_LOG_LEVEL", "WARNING")
    ws = tmp_path / "ws"
    L.setup_logging(ws)
    log = L.get_logger("unit")
    log.info("noisy")
    log.warning("important")
    body = _text(ws)
    assert "noisy" not in body
    assert "important" in body


def test_rotation_actually_rotates(tmp_path):
    ws = tmp_path / "ws"
    L.setup_logging(ws, max_bytes=600, backups=2)
    log = L.get_logger("unit")
    for i in range(200):
        log.info("line %03d %s", i, "x" * 30)
    _flush()
    assert L.log_path(ws).exists()
    assert (L.log_path(ws).parent / "uiu.log.1").exists(), "超过 maxBytes 必须轮转"


def test_logging_failure_does_not_break_the_app(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    (ws / "logs").write_text("not a directory", encoding="utf-8")
    L.setup_logging(ws)                      # 不能抛
    L.get_logger("unit").error("still callable")   # 也不能抛
    assert _our_file_handlers(ws) == [], "日志目录不可用时不要留下死 handler"


def test_corrupt_state_backup_is_logged(tmp_path):
    ws = tmp_path / "ws"
    L.setup_logging(ws)
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    from uiu._atomic import load_json_tolerant

    assert load_json_tolerant(bad, {"fallback": 1}) == {"fallback": 1}
    assert "损坏文件已备份" in _text(ws)


def test_daemon_logs_start_and_stop(tmp_path, monkeypatch):
    from uiu import daemon

    # 守护进程状态目录默认在 ~/.uiu，测试必须重定向
    monkeypatch.setenv("UIU_HOME", str(tmp_path / "uiu-home"))
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    stop = threading.Event()
    stop.set()                                # 立刻退出循环
    daemon.run_daemon(ws, interval=0.01, stop_event=stop)
    body = _text(ws)
    assert "started" in body and "stopped" in body
    assert "[uiu.daemon]" in body


def test_gateway_logs_bind_and_never_the_token(tmp_path, monkeypatch):
    from uiu.config import AppConfig
    from uiu.gateway import Gateway
    from uiu.workspace import Workspace

    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    monkeypatch.setenv("UIU_GATEWAY_TOKEN", "super-secret-token")
    L.setup_logging(ws)               # Gateway.run() 会做这一步
    gw = Gateway(AppConfig(), Workspace(root=ws))
    server = gw._start_http_server(0, "127.0.0.1")
    try:
        body = _text(ws)
        assert "webhook server: bind=127.0.0.1" in body
        assert "auth=已启用" in body
        assert "super-secret-token" not in body, "日志里绝不能出现 token 明文"
    finally:
        server.shutdown()
        server.server_close()


def test_cron_job_failure_is_logged(tmp_path, monkeypatch):
    from uiu import cron
    from uiu import log as logmod

    ws = tmp_path / "ws"
    logmod.setup_logging(ws)
    cron.add_job(ws, "boom", "1d", "whatever")
    # "1d" 的 next_run 在明天，tick 不会跑；手动改成已到期
    jobs = cron.load_jobs(ws)
    for job in jobs:
        job["next_run"] = 0
    cron.save_jobs(ws, jobs)

    def explode(ws_path, job):
        raise RuntimeError("job blew up")

    monkeypatch.setattr(cron, "run_job", explode)
    ran = cron.tick(ws)
    assert ran == []
    body = _text(ws)
    assert "job boom failed" in body
    assert "job blew up" in body
