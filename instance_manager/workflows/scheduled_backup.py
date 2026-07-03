"""Scheduled automated backups for an instance via a systemd timer."""

from __future__ import annotations

from ..i18n import tf
from ..models import InstanceConfig
from ..planners import plan_remove_scheduled_backup, plan_scheduled_backup
from ..prompts import ask_bool, ask_int, ask_text, choose
from ..system import run
from ..ui import level_text, title
from .common import _execute_plan, _filestore_path, _is_safe_path_component

_ONCALENDAR = {
    'Daily (02:30)': "*-*-* 02:30:00",
    'Weekly (Sunday 03:00)': "Sun *-*-* 03:00:00",
    'Monthly (day 1, 03:30)': "*-*-01 03:30:00",
}


def _configure_schedule(config: InstanceConfig) -> None:
    print(f"\n{title('Configure scheduled backup')}")
    print(
        level_text(
            "INFO",
            "The backup runs as root using 'sudo -u postgres pg_dump' (local DB, no password).",
        )
    )
    db_name = ask_text('Database to back up', config.db_name or config.instance, required=True)
    if not _is_safe_path_component(db_name):
        print(level_text("ERROR", 'Invalid database name.'))
        return
    backup_dir = ask_text('Destination directory', f"/var/backups/{config.instance}", required=True)
    include_filestore = ask_bool('Include the filestore as well?', True)
    keep = ask_int('How many backups to keep (retention)?', 7, min_value=1, max_value=365)
    schedule = choose('Frequency', [*list(_ONCALENDAR), 'Back'], default_index=0)
    if schedule in {"", 'Back'}:
        return

    commands = plan_scheduled_backup(
        config,
        db_name=db_name,
        backup_dir=backup_dir,
        filestore_dir=_filestore_path(config, db_name),
        oncalendar=_ONCALENDAR[schedule],
        keep=keep,
        include_filestore=include_filestore,
    )
    _execute_plan(commands)


def _show_schedule_status(config: InstanceConfig) -> None:
    name = f"odoo-backup-{config.instance}"
    print(f"\n{title('Scheduled-backup status')}")
    status = run(f"systemctl status {name}.timer --no-pager -n 5 2>&1", check=False)
    print(status.stdout.strip() or '(no timer configured)')
    nxt = run(f"systemctl list-timers {name}.timer --no-pager 2>&1", check=False)
    if nxt.stdout.strip():
        print("\n" + nxt.stdout.strip())


def _remove_schedule(config: InstanceConfig) -> None:
    _execute_plan(plan_remove_scheduled_backup(config))


def manage_scheduled_backup(config: InstanceConfig) -> None:
    while True:
        action = choose(
            tf('Scheduled backups: {}', config.instance),
            [
                'Configure scheduled backup',
                'Show status',
                'Remove schedule',
                'Back',
            ],
            default_index=None,
        )
        if action in {"", 'Back'}:
            return
        if action == 'Configure scheduled backup':
            _configure_schedule(config)
        elif action == 'Show status':
            _show_schedule_status(config)
        elif action == 'Remove schedule':
            _remove_schedule(config)
