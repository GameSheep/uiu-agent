"""CLI 子命令门面（审计 §2.1：原 1,676 行上帝模块已按域拆分）。

实现分别在 cli_shared / cli_basic / cli_model / cli_channels / cli_skills /
cli_sessions / cli_automation / cli_ops；这里只做再导出，保证既有引用
（from uiu.commands import cmd_x / _workspace 等）不受影响。
"""

from .cli_basic import (
    cmd_init,
    cmd_show,
    cmd_version,
    cmd_audit,
    cmd_backup,
    cmd_restore,
    cmd_trash,
)

from .cli_model import (
    cmd_model,
    cmd_config,
    cmd_plugins,
    _model_wizard,
    _test_model_connection,
    _resolve_key_env,
    _setup_playwright_browsers,
    _setup_playwright_browsers_async,
)

from .cli_channels import (
    cmd_channel,
    _default_secret_env,
    _parse_options,
)

from .cli_skills import (
    cmd_skills,
    _update_default_skills,
)

from .cli_sessions import (
    cmd_sessions,
    cmd_macro,
    cmd_quick,
)

from .cli_automation import (
    cmd_cron,
    cmd_daemon,
)

from .cli_ops import (
    cmd_doctor,
    cmd_update,
    cmd_publish,
    cmd_serve,
    _verify_version_consistency,
)

from .cli_shared import (
    _workspace,
    _print_ok,
    _print_err,
    _confirm,
    _session_cap,
    _session_age_days,
    _is_git_source_install,
    _plugins_dir,
)

__all__ = [
    "_workspace",
    "_print_ok",
    "_print_err",
    "_confirm",
    "cmd_init",
    "_setup_playwright_browsers_async",
    "_setup_playwright_browsers",
    "cmd_show",
    "cmd_model",
    "_model_wizard",
    "_test_model_connection",
    "_resolve_key_env",
    "cmd_config",
    "cmd_skills",
    "cmd_channel",
    "_default_secret_env",
    "_parse_options",
    "_is_git_source_install",
    "cmd_update",
    "_update_default_skills",
    "cmd_serve",
    "cmd_version",
    "_plugins_dir",
    "cmd_plugins",
    "_verify_version_consistency",
    "cmd_publish",
    "cmd_cron",
    "cmd_sessions",
    "cmd_doctor",
    "cmd_macro",
    "cmd_quick",
    "cmd_daemon",
    "cmd_backup",
    "cmd_restore",
    "cmd_audit",
    "_session_cap",
    "_session_age_days",
    "cmd_trash",
]
