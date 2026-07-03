"""Disk usage report and backup retention cleanup for an instance."""

from __future__ import annotations

from ..i18n import tf
from ..models import InstanceConfig
from ..planners import plan_backup_retention
from ..prompts import ask_int, ask_text, choose
from ..system import path_exists, run
from ..ui import level_text, render_table, title
from .common import _execute_plan, _quote, _resolve_data_dir


def _size_of(path: str) -> str:
    if not path_exists(path):
        return '(does not exist)'
    result = run(f"du -sh {_quote(path)} 2>/dev/null | cut -f1", check=False)
    return result.stdout.strip() or "?"


def _log_size(config: InstanceConfig) -> str:
    result = run(
        f"du -ch {_quote(config.odoo_log_file)}* 2>/dev/null | tail -1 | cut -f1",
        check=False,
    )
    return result.stdout.strip() or '(no logs)'


def _disk_usage_report(config: InstanceConfig, backup_dir: str) -> None:
    data_dir = _resolve_data_dir(config)
    print(f"\n{title(tf('Disk usage: {}', config.instance))}")
    rows = [
        ['Instance home', config.odoo_home, _size_of(config.odoo_home)],
        ["Data dir (filestore)", data_dir, _size_of(data_dir)],
        ['Odoo logs', f"{config.odoo_log_file}*", _log_size(config)],
        ["Backups directory", backup_dir, _size_of(backup_dir)],
    ]
    print(render_table(['Item', 'Path', 'Size'], rows))

    print(f"\n{title('Free space of the data-dir filesystem')}")
    df = run(f"df -Ph {_quote(data_dir)} 2>/dev/null", check=False)
    print(df.stdout.strip() or '(not measurable)')

    if path_exists(backup_dir):
        print(f"\n{title('Present backups (most recent first)')}")
        listing = run(
            f"ls -lht {_quote(backup_dir)} 2>/dev/null | grep -E '\\.dump$|\\.tar\\.gz$' | head -20",
            check=False,
        )
        print(listing.stdout.strip() or '(no backups)')


def _cleanup_old_backups(config: InstanceConfig, backup_dir: str) -> None:
    if not path_exists(backup_dir):
        print(level_text("INFO", tf('Backup directory does not exist: {}', backup_dir)))
        return
    keep = ask_int(
        'How many recent backups to keep (per kind)?', 5, min_value=1, max_value=365
    )
    commands = plan_backup_retention(config, backup_dir, keep)
    _execute_plan(commands)


def manage_disk_usage(config: InstanceConfig) -> None:
    backup_dir = ask_text(
        'Backup directory to review', f"/var/backups/{config.instance}", required=True
    )
    while True:
        action = choose(
            tf('Disk usage and cleanup: {}', config.instance),
            [
                'Show disk usage',
                'Prune old backups (retention)',
                'Back',
            ],
            default_index=None,
        )
        if action in {"", 'Back'}:
            return
        if action == 'Show disk usage':
            _disk_usage_report(config, backup_dir)
        elif action == 'Prune old backups (retention)':
            _cleanup_old_backups(config, backup_dir)
