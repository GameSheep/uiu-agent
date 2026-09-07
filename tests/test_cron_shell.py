"""Cron shell (no_agent) jobs — run commands without LLM."""

import time


def test_add_job_run_shell_persisted(tmp_path):
    import uiu.cron as cron
    ws = tmp_path / "ws"
    job = cron.add_job(ws, "backup", "1d", "echo hi", run_shell=True)
    assert job["run_shell"] is True
    saved = cron.load_jobs(ws)[0]
    assert saved["run_shell"] is True and saved["task"] == "echo hi"


def test_default_job_is_agent(tmp_path):
    import uiu.cron as cron
    ws = tmp_path / "ws"
    job = cron.add_job(ws, "agentjob", "1d", "do a thing")
    assert job.get("run_shell") is False


def test_run_job_shell_executes_and_writes_md(tmp_path):
    """tick a due shell job end-to-end: output file contains command stdout."""
    import uiu.cron as cron
    ws = tmp_path / "ws"
    job = cron.add_job(ws, "sh1", "once 2000-01-01T00:00:00", "echo hello-from-cron", run_shell=True)
    ran = cron.tick(ws)
    assert len(ran) == 1
    text = __import__("pathlib").Path(ran[0]).read_text(encoding="utf-8")
    assert "hello-from-cron" in text
    assert cron.load_jobs(ws)[0]["enabled"] is False  # once 跑完即停


def test_run_job_shell_rejects_dangerous_command(tmp_path):
    import uiu.cron as cron
    ws = tmp_path / "ws"
    job = cron.add_job(ws, "bad", "1d", "shutdown -s -t 0", run_shell=True)
    out = cron.run_job(ws, job)
    text = __import__("pathlib").Path(out).read_text(encoding="utf-8")
    assert "危险命令被拦截" in text


def test_run_job_shell_handles_nonzero_exit(tmp_path):
    import uiu.cron as cron
    ws = tmp_path / "ws"
    job = cron.add_job(ws, "fail", "1d", "python -c \"import sys; sys.exit(3)\"", run_shell=True)
    out = cron.run_job(ws, job)
    text = __import__("pathlib").Path(out).read_text(encoding="utf-8")
    assert "exit code: 3" in text


def test_cli_cron_add_shell_flag(tmp_path):
    import argparse
    from uiu.commands import cmd_cron
    ws = tmp_path / "ws"
    ns = argparse.Namespace(workspace=str(ws), action="add", name="k", schedule="1d",
                            task="echo x", shell=True)
    assert cmd_cron(ns) == 0
    from uiu.cron import load_jobs
    assert load_jobs(ws)[0]["run_shell"] is True
