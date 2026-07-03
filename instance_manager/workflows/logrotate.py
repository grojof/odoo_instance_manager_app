"""Configure and query system logrotate for an instance's Odoo log."""

from __future__ import annotations

from ..i18n import tf
from ..models import InstanceConfig
from ..planners import plan_logrotate_config
from ..prompts import ask_bool, ask_int, ask_text, choose
from ..system import path_exists, read_odoo_conf, run
from ..ui import level_text, render_table, title
from .common import _execute_plan, _quote, _read_text_file


def _nginx_logs_covered_by_system() -> bool:
    """True if the distribution's `/etc/logrotate.d/nginx` already rotates the
    per-instance Nginx logs (its standard `/var/log/nginx/*.log` glob covers them)."""
    content = _read_text_file("/etc/logrotate.d/nginx")
    if not content:
        return False
    return "/var/log/nginx/*.log" in content or "/var/log/nginx/*" in content


def _query_log_rotation(config: InstanceConfig) -> None:
    lr_file = config.logrotate_config_file
    lr_present = path_exists(lr_file)
    policy_content = _read_text_file(lr_file) if lr_present else ""
    odoo_active = lr_present and config.odoo_log_file in policy_content
    conf_values = read_odoo_conf(config.odoo_conf_file)
    obsolete_key = "logrotate" in conf_values

    print(f"\n{title('Instance log rotation')}")
    rows = [
        ['Odoo log', config.odoo_log_file],
        [
            'Odoo log rotation',
            level_text("OK", 'ACTIVE (system logrotate)')
            if odoo_active
            else level_text("MISSING", 'INACTIVE'),
        ],
        ['logrotate.d policy', lr_file if lr_present else f"{lr_file} (no configurada)"],
    ]
    print(render_table(['Item', 'Value'], rows))

    if lr_present:
        print(f"\n{title('Current logrotate policy')}")
        print(policy_content.strip() or '(empty)')
        print(f"\n{title('Preview (logrotate -d)')}")
        dry = run(f"logrotate -d {_quote(lr_file)}", check=False)
        print((dry.stdout or dry.stderr).strip() or '(no output)')
    else:
        print(level_text("INFO", 'There is no system logrotate policy for this instance.'))

    print(f"\n{title('Odoo log files')}")
    sizes = run(f"ls -lh {_quote(config.odoo_log_file)}* 2>/dev/null", check=False)
    print(sizes.stdout.strip() or '(no log files)')

    if _nginx_logs_covered_by_system():
        print(level_text("INFO", 'Nginx logs: rotated by the system logrotate (/etc/logrotate.d/nginx).'))
    elif config.nginx_access_log in policy_content:
        print(level_text("OK", 'Nginx logs: rotated by this policy (create + reopen SIGUSR1).'))
    else:
        print(
            level_text(
                "WARN",
                'Nginx logs: no rotation coverage detected; consider including them when configuring.',
            )
        )
    if obsolete_key:
        print(
            level_text(
                "INFO",
                "The odoo.conf contains a 'logrotate' key (obsolete since Odoo 13, ignored); you can clean it up when configuring.",
            )
        )


def _configure_log_rotation(config: InstanceConfig) -> None:
    print(f"\n{title('Configure log rotation (system logrotate)')}")
    frequency = choose(
        'Rotation frequency',
        ["weekly", "daily", "monthly"],
        default_index=0,
    )
    if not frequency:
        return
    rotate_count = ask_int(
        'Number of rotations to keep', 14, min_value=1, max_value=365
    )
    compress = ask_bool('Compress rotated logs?', True)
    maxsize = ""
    if ask_bool('Also rotate when a size is exceeded?', False):
        maxsize = ask_text('Maximum size (e.g. 50M, 1G)', "50M", required=True)

    conf_values = read_odoo_conf(config.odoo_conf_file)
    remove_obsolete = False
    if "logrotate" in conf_values:
        print(
            level_text(
                "INFO",
                "The odoo.conf has a 'logrotate' key (obsolete since Odoo 13; Odoo ignores it).",
            )
        )
        remove_obsolete = ask_bool('Remove it from the odoo.conf?', True)

    include_nginx = False
    if _nginx_logs_covered_by_system():
        print(
            level_text(
                "INFO",
                'Nginx logs are already covered by the system logrotate (/etc/logrotate.d/nginx); not added here to avoid double rotation.',
            )
        )
    else:
        print(
            level_text(
                "WARN",
                "The system logrotate does not cover the instance's Nginx logs.",
            )
        )
        include_nginx = ask_bool(
            "Also include the instance's Nginx logs (create + reopen SIGUSR1)?",
            True,
        )

    commands = plan_logrotate_config(
        config,
        frequency=frequency,
        rotate_count=rotate_count,
        compress=compress,
        maxsize=maxsize,
        remove_obsolete_odoo_key=remove_obsolete,
        include_nginx=include_nginx,
    )
    _execute_plan(commands)


def manage_log_rotation(config: InstanceConfig) -> None:
    while True:
        action = choose(
            tf('Log rotation: {}', config.instance),
            [
                'Show current rotation',
                'Configure rotation (system logrotate)',
                'Back',
            ],
            default_index=None,
        )
        if action in {"", 'Back'}:
            return
        if action == 'Show current rotation':
            _query_log_rotation(config)
        elif action == 'Configure rotation (system logrotate)':
            _configure_log_rotation(config)
