"""Backup, restore, and duplicate instance data (database + filestore)."""

from __future__ import annotations

import datetime
import re
import uuid

from ..i18n import tf
from ..models import InstanceConfig
from ..prompts import (
    ask_bool,
    ask_text,
    choose,
    confirm_with_phrase,
    select_file_path,
)
from ..system import (
    Command,
    database_exists,
    path_exists,
    service_exists,
)
from ..ui import level_text
from .common import (
    DbCredentials,
    _ask_db_credentials,
    _execute_plan,
    _filestore_path,
    _is_safe_path_component,
    _pick_db_name,
    _quote,
)

_SAFE_DB_NAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,62}$")


def _is_safe_db_name(name: str) -> bool:
    """A PostgreSQL database name safe to interpolate into SQL identifiers and
    string literals: no quotes, semicolons, or whitespace, max 63 chars."""
    return bool(_SAFE_DB_NAME_RE.fullmatch(name or ""))


def _duplicate_db_command(
    db_host: str,
    db_port: int,
    db_user: str,
    db_password: str,
    source_db: str,
    target_db: str,
) -> str:
    """Build the shell script that duplicates ``source_db`` into ``target_db`` via
    a template copy, freeing the source of active sessions first.

    A ``CREATE DATABASE … TEMPLATE`` needs no other sessions on the template, so we
    block new connections, terminate existing ones, run ``createdb -T``, and — via a
    ``trap … EXIT`` — always re-enable connections to the source (even if the copy
    fails), so the operator never has to stop the source service. Runs as the
    instance's own role (owner of its database); no superuser needed.

    Callers MUST pass names that satisfy :func:`_is_safe_db_name`; ``source_db`` is
    interpolated into SQL, the rest are shell-quoted. Executed via ``bash -lc``.
    """
    psql = f"psql -h {_quote(db_host)} -p {db_port} -U {_quote(db_user)} -d postgres"
    return "\n".join(
        [
            "set -e",
            f"export PGPASSWORD={_quote(db_password)}",
            # Always re-open the source, even if the copy below fails.
            f"reenable() {{ {psql} -c 'ALTER DATABASE \"{source_db}\" WITH ALLOW_CONNECTIONS true;' >/dev/null 2>&1 || true; }}",
            "trap reenable EXIT",
            f"{psql} -v ON_ERROR_STOP=1 -c 'ALTER DATABASE \"{source_db}\" WITH ALLOW_CONNECTIONS false;'",
            f"{psql} -c \"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{source_db}' AND pid <> pg_backend_pid();\"",
            f"createdb -h {_quote(db_host)} -p {db_port} -U {_quote(db_user)} -T {_quote(source_db)} -O {_quote(db_user)} {_quote(target_db)}",
        ]
    )


def _post_db_mode_commands(
    db_host: str,
    db_port: int,
    db_user: str,
    db_password: str,
    target_db: str,
    migration_mode: str,
    neutralize: bool,
) -> list[Command]:
    commands: list[Command] = []
    if migration_mode == 'Copied (new UUID on target)':
        new_uuid = str(uuid.uuid4())
        sql_uuid = (
            "INSERT INTO ir_config_parameter (key, value, create_uid, create_date, write_uid, write_date) "
            f"VALUES ('database.uuid', '{new_uuid}', 1, NOW(), 1, NOW()) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, write_date = NOW();"
        )
        commands.append(
            Command(
                'Regenerate database.uuid on the target (Copied mode)',
                f'PGPASSWORD={_quote(db_password)} psql -h {_quote(db_host)} -p {db_port} -U {_quote(db_user)} -d {_quote(target_db)} -c "{sql_uuid}"',
            )
        )

    if neutralize:
        commands.extend(
            [
                Command(
                    'Neutralize cron on the target (if present)',
                    f'PGPASSWORD={_quote(db_password)} psql -h {_quote(db_host)} -p {db_port} -U {_quote(db_user)} -d {_quote(target_db)} -c "UPDATE ir_cron SET active = false;" || true',
                ),
                Command(
                    'Neutralize outgoing mail servers (if present)',
                    f'PGPASSWORD={_quote(db_password)} psql -h {_quote(db_host)} -p {db_port} -U {_quote(db_user)} -d {_quote(target_db)} -c "UPDATE ir_mail_server SET active = false;" || true',
                ),
                Command(
                    'Neutralize fetchmail (if present)',
                    f'PGPASSWORD={_quote(db_password)} psql -h {_quote(db_host)} -p {db_port} -U {_quote(db_user)} -d {_quote(target_db)} -c "UPDATE fetchmail_server SET active = false;" || true',
                ),
            ]
        )

    return commands


def _backup_instance(
    config: InstanceConfig, cached: DbCredentials | None = None
) -> DbCredentials | None:
    creds = _ask_db_credentials(config.instance, cached)
    db_name = _pick_db_name(creds, 'Source DB for backup', required=True)
    if not db_name:
        print(level_text("INFO", 'No source DB, operation cancelled.'))
        return creds
    if not _is_safe_path_component(db_name):
        print(level_text("ERROR", 'Invalid DB name for building the filestore path.'))
        return creds

    db_host, db_port, db_user, db_password = creds.host, creds.port, creds.user, creds.password

    backup_dir = ask_text(
        'Backup destination directory', f"/var/backups/{config.instance}", required=True
    )
    backup_mode = choose(
        'Backup type',
        ['Database only', 'Filestore only', 'Database + Filestore'],
        default_index=None,
    )
    if not backup_mode:
        print(level_text("INFO", 'Operation cancelled.'))
        return creds

    filestore_dir = _filestore_path(config, db_name)
    quoted_backup_dir = _quote(backup_dir)
    # One timestamp for the whole operation so the DB dump and the filestore
    # archive of the same backup share a suffix and can be paired.
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    dump_path = f"{backup_dir}/{config.instance}_{ts}.dump"
    archive_path = f"{backup_dir}/{config.instance}_{ts}.filestore.tar.gz"
    commands: list[Command] = [
        Command('Create backup directory', f"mkdir -p {quoted_backup_dir}")
    ]

    if backup_mode in {'Database only', 'Database + Filestore'}:
        commands.append(
            Command(
                'Export DB backup (custom format, atomic)',
                f"TMP={_quote(dump_path + '.partial')} && "
                f"PGPASSWORD={_quote(db_password)} pg_dump -h {_quote(db_host)} -p {db_port} -U {_quote(db_user)} -Fc -f \"$TMP\" {_quote(db_name)} && "
                f"mv \"$TMP\" {_quote(dump_path)} || {{ rm -f \"$TMP\"; exit 1; }}",
            )
        )

    if backup_mode in {'Filestore only', 'Database + Filestore'}:
        commands.append(
            Command(
                'Export filestore backup (atomic)',
                f"TMP={_quote(archive_path + '.partial')} && "
                f"test -d {_quote(filestore_dir)} && "
                f"tar -czf \"$TMP\" -C {_quote(filestore_dir)} . && "
                f"mv \"$TMP\" {_quote(archive_path)} || {{ rm -f \"$TMP\"; exit 1; }}",
            )
        )

    _execute_plan(commands)
    print(level_text("INFO", tf('Backup suffix: {}', ts)))
    return creds


def _restore_backup(
    config: InstanceConfig, cached: DbCredentials | None = None
) -> DbCredentials | None:
    restore_mode = choose(
        'Restore type',
        ['Database only', 'Filestore only', 'Database + Filestore'],
        default_index=None,
    )
    if not restore_mode:
        print(level_text("INFO", 'Operation cancelled.'))
        return cached

    target_db = ask_text('Target DB', config.instance, required=True)
    if not _is_safe_path_component(target_db):
        print(level_text("ERROR", 'Invalid target DB name for building the filestore path.'))
        return cached
    migration_mode = choose(
        'Operation mode (Odoo equivalent)',
        ['Copied (new UUID on target)', 'Moved (keep UUID)'],
        default_index=None,
    )
    if not migration_mode:
        print(level_text("INFO", 'Operation cancelled.'))
        return cached
    neutralize = ask_bool('Neutralize the target?', True)

    creds = _ask_db_credentials(config.instance, cached)
    db_host, db_port, db_user, db_password = creds.host, creds.port, creds.user, creds.password

    commands: list[Command] = []

    if restore_mode in {'Database only', 'Database + Filestore'}:
        if database_exists(target_db):
            print(level_text("ERROR", tf('The target DB already exists: {}', target_db)))
            return creds

        print(level_text("INFO", 'Select a dump file (.dump)'))
        dump_file = select_file_path(".", 'Database dump', (".dump",))
        if not dump_file:
            print(level_text("INFO", 'Operation cancelled.'))
            return creds
        commands.extend(
            [
                Command(
                    'Create target DB',
                    f"PGPASSWORD={_quote(db_password)} createdb -h {_quote(db_host)} -p {db_port} -U {_quote(db_user)} -O {_quote(db_user)} {_quote(target_db)}",
                ),
                Command(
                    'Restore the dump into the target DB',
                    f"PGPASSWORD={_quote(db_password)} pg_restore -h {_quote(db_host)} -p {db_port} -U {_quote(db_user)} -d {_quote(target_db)} --no-owner --no-privileges {_quote(dump_file)}",
                ),
            ]
        )
        commands.extend(
            _post_db_mode_commands(
                db_host=db_host,
                db_port=db_port,
                db_user=db_user,
                db_password=db_password,
                target_db=target_db,
                migration_mode=migration_mode,
                neutralize=neutralize,
            )
        )

    if restore_mode in {'Filestore only', 'Database + Filestore'}:
        print(level_text("INFO", 'Select a filestore backup file (.tar.gz)'))
        filestore_backup = select_file_path(".", 'Filestore backup', (".tar.gz", ".tgz"))
        if not filestore_backup:
            print(level_text("INFO", 'Operation cancelled.'))
            return creds
        target_filestore = _filestore_path(config, target_db)
        overwrite_store = False
        if path_exists(target_filestore):
            overwrite_store = ask_bool(
                'The target filestore exists — overwrite?', False
            )
            if not overwrite_store:
                print(level_text("INFO", 'Filestore restore cancelled due to a conflict.'))
                return creds

        commands.append(
            Command(
                'Create the filestore base path', f"mkdir -p {_quote(target_filestore)}"
            )
        )
        if overwrite_store:
            commands.append(
                Command(
                    'Remove the previous filestore', f"rm -rf {_quote(target_filestore)}/*"
                )
            )
        commands.append(
            Command(
                'Restore the filestore into the target',
                f"tar -xzf {_quote(filestore_backup)} -C {_quote(target_filestore)}",
            )
        )

    if not confirm_with_phrase(
        'Sensitive restore action detected.',
        f"RESTORE {config.instance}",
    ):
        print(level_text("INFO", 'Invalid confirmation. Operation cancelled.'))
        return creds

    _execute_plan(commands)
    return creds


def _duplicate_instance(
    config: InstanceConfig, cached: DbCredentials | None = None
) -> DbCredentials | None:
    creds = _ask_db_credentials(config.instance, cached)
    source_db = _pick_db_name(creds, 'Source DB to duplicate', required=True)
    if not source_db:
        print(level_text("INFO", 'No source DB, operation cancelled.'))
        return creds

    target_instance = ask_text('New target instance', "", required=True)
    target_db = ask_text('New target DB', target_instance, required=True)

    target_config = InstanceConfig(instance=target_instance)
    target_config.db_user = target_db
    try:
        target_config.validate_identifiers()
    except ValueError as error:
        print(level_text("ERROR", str(error)))
        return creds
    if path_exists(target_config.odoo_home):
        print(level_text("ERROR", tf('Already exists: {}', target_config.odoo_home)))
        return creds
    if service_exists(target_instance):
        print(level_text("ERROR", tf('systemd service already exists: {}', target_instance)))
        return creds
    if database_exists(target_db):
        print(level_text("ERROR", tf('Target DB already exists: {}', target_db)))
        return creds

    if not _is_safe_db_name(source_db) or not _is_safe_db_name(target_db):
        print(
            level_text(
                "ERROR",
                'Unsafe database name (only letters, digits, and _ . - are allowed).',
            )
        )
        return creds

    db_host, db_port, db_user, db_password = creds.host, creds.port, creds.user, creds.password

    migration_mode = choose(
        'Duplication mode',
        ['Copied (new UUID on target)', 'Moved (keep UUID)'],
        default_index=None,
    )
    if not migration_mode:
        print(level_text("INFO", 'Operation cancelled.'))
        return creds
    neutralize = ask_bool('Neutralize the duplicated DB?', True)
    duplicate_filestore = ask_bool('Also duplicate the filestore?', True)

    commands: list[Command] = [
        Command(
            'Duplicate DB via template (frees the source of active sessions)',
            _duplicate_db_command(
                db_host, db_port, db_user, db_password, source_db, target_db
            ),
        )
    ]

    commands.extend(
        _post_db_mode_commands(
            db_host=db_host,
            db_port=db_port,
            db_user=db_user,
            db_password=db_password,
            target_db=target_db,
            migration_mode=migration_mode,
            neutralize=neutralize,
        )
    )

    if duplicate_filestore:
        source_filestore = _filestore_path(config, source_db)
        # Target filestore must resolve under the TARGET instance's data dir, not
        # the source instance's, or the duplicated instance starts without it.
        target_filestore = _filestore_path(target_config, target_db)
        if path_exists(target_filestore):
            print(level_text("ERROR", tf('Target filestore already exists: {}', target_filestore)))
            return creds

        target_parent = target_filestore.rsplit("/", 1)[0]
        commands.extend(
            [
                Command(
                    'Create the target filestore base path',
                    f"mkdir -p {_quote(target_parent)}",
                ),
                Command(
                    'Duplicate the filestore',
                    f"cp -a {_quote(source_filestore)} {_quote(target_filestore)}",
                ),
            ]
        )

    if not confirm_with_phrase(
        'Sensitive duplication action detected.',
        f"DUPLICAR {config.instance}",
    ):
        print(level_text("INFO", 'Invalid confirmation. Operation cancelled.'))
        return creds

    _execute_plan(commands)
    return creds
