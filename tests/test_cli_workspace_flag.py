"""CLI arg-normalization tests — --workspace accepted before or after subcommand."""

import os


def test_workspace_flag_after_subcommand(tmp_cwd):
    """`uiu init --workspace X` must work (argparse only knows the top-level flag)."""
    from uiu import main
    ws = tmp_cwd / "ws-after"
    rc = main.main(["init", "--workspace", str(ws)])
    assert rc == 0, rc
    assert (ws / "config.yaml").exists()
    assert (ws / "SOUL.md").exists()


def test_workspace_flag_before_subcommand(tmp_cwd):
    from uiu import main
    ws = tmp_cwd / "ws-before"
    rc = main.main(["--workspace", str(ws), "init"])
    assert rc == 0, rc
    assert (ws / "config.yaml").exists()


def test_workspace_flag_with_config(tmp_cwd):
    from uiu import main
    ws = tmp_cwd / "ws-cfg"
    rc = main.main(["init", "--workspace", str(ws)])
    assert rc == 0
    rc = main.main(["config", "--set-secret", "A=1", "--workspace", str(ws)])
    assert rc == 0, rc
    rc = main.main(["--workspace", str(ws), "config", "--list"])
    assert rc == 0, rc


def test_version_unaffected_by_normalizer():
    from uiu import main
    assert main.main(["version"]) == 0
    assert main.main(["--version"]) == 0
