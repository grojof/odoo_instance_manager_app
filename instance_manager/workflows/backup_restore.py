"""Backup, restore, and duplicate instance data (database + filestore)."""

from __future__ import annotations

import datetime
import os
import re
import uuid

from ..i18n import tf
from ..models import InstanceConfig
from ..planners import (
    _is_local_db_host,
    plan_ensure_db_role,
    plan_nginx_http,
    plan_nginx_https,
    plan_odoo_base_setup,
)
from ..prompts import (
    ask_bool,
    ask_int,
    ask_text,
    choose,
    confirm_with_phrase,
    select_file_path,
)
from ..system import (
    Command,
    database_exists,
    detect_nginx_version,
    path_exists,
    read_odoo_conf,
    run,
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
from .install import (
    _choose_nginx_mode,
    _maybe_plan_certs,
    _maybe_plan_wkhtmltopdf,
    _prompt_production_hardening,
    _prompt_secret,
    _suggest_instance_ports,
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


def _psql_target(
    db_host: str, db_port: int, db_user: str, db_password: str, target_db: str
) -> str:
    """A psql invocation pointed at ``target_db`` using client credentials."""
    return (
        f"PGPASSWORD={_quote(db_password)} psql -h {_quote(db_host)} -p {db_port} "
        f"-U {_quote(db_user)} -d {_quote(target_db)}"
    )


def _psql_target_local(target_db: str) -> str:
    """A psql invocation pointed at ``target_db`` as the local postgres superuser."""
    return f"sudo -u postgres psql -d {_quote(target_db)}"


def _post_db_mode_commands(
    psql_target: str,
    migration_mode: str,
    neutralize: bool,
) -> list[Command]:
    """Apply Odoo migration semantics to an already-restored target database.

    ``psql_target`` is a psql invocation already pointed at the target DB (built by
    :func:`_psql_target` or :func:`_psql_target_local`), so the same logic serves
    both the credential-based restore and the local, superuser-driven duplication.
    """
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
                f'{psql_target} -c "{sql_uuid}"',
            )
        )

    if neutralize:
        commands.extend(
            [
                Command(
                    'Neutralize cron on the target (if present)',
                    f'{psql_target} -c "UPDATE ir_cron SET active = false;" || true',
                ),
                Command(
                    'Neutralize outgoing mail servers (if present)',
                    f'{psql_target} -c "UPDATE ir_mail_server SET active = false;" || true',
                ),
                Command(
                    'Neutralize fetchmail (if present)',
                    f'{psql_target} -c "UPDATE fetchmail_server SET active = false;" || true',
                ),
            ]
        )

    return commands


def _seed_db_commands(source_db: str, target_db: str, target_owner: str, method: str) -> list[Command]:
    """Seed ``target_db`` from ``source_db`` on the **local** server (via
    ``sudo -u postgres``), owned by ``target_owner``.

    ``method="template"`` frees the source of sessions and does a fast template copy
    (correct when the target keeps the source's owner). ``method="dump"`` restores a
    ``pg_dump`` with ``--role`` so every object is re-owned by ``target_owner`` —
    correct for a cross-user target (production→development). Names MUST be safe
    (:func:`_is_safe_db_name`)."""
    if method == "template":
        return [
            Command(
                'Terminate connections to the source DB',
                "sudo -u postgres psql -d postgres -c "
                f"\"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{source_db}' AND pid <> pg_backend_pid();\" || true",
            ),
            Command(
                'Seed target DB via template copy',
                f"sudo -u postgres createdb -T {_quote(source_db)} -O {_quote(target_owner)} {_quote(target_db)}",
            ),
        ]
    return [
        Command(
            'Create empty target DB owned by the target role',
            f"sudo -u postgres createdb -O {_quote(target_owner)} {_quote(target_db)}",
        ),
        Command(
            'Seed target DB via pg_dump | pg_restore (re-owned by the target role)',
            "set -o pipefail; "
            f"sudo -u postgres pg_dump -Fc {_quote(source_db)} | "
            f"sudo -u postgres pg_restore -d {_quote(target_db)} --no-owner --role={_quote(target_owner)} --no-privileges",
        ),
    ]


def _drop_db_commands(target_db: str) -> list[Command]:
    """Terminate connections to ``target_db`` and drop it (local, superuser)."""
    return [
        Command(
            'Terminate connections to the target DB',
            "sudo -u postgres psql -d postgres -c "
            f"\"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{target_db}' AND pid <> pg_backend_pid();\" || true",
        ),
        Command(
            'Drop the target DB (if it exists)',
            f"sudo -u postgres dropdb --if-exists {_quote(target_db)}",
        ),
    ]


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
                _psql_target(db_host, db_port, db_user, db_password, target_db),
                migration_mode,
                neutralize,
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


def _detect_source_repo_branch(config: InstanceConfig) -> str:
    """Best-effort detection of the source instance's checked-out Odoo branch, so a
    replica clones the same version."""
    result = run(
        f"git -C {_quote(config.odoo_home + '/odoo')} rev-parse --abbrev-ref HEAD 2>/dev/null",
        check=False,
    )
    branch = result.stdout.strip()
    return branch if branch and branch != "HEAD" else ""


def _nginx_server_name_in_use(domain: str, directory: str = "/etc/nginx/sites-enabled") -> bool:
    """True if ``domain`` is already a ``server_name`` in an enabled Nginx vhost.

    Nginx keeps the first vhost for a given ``server_name`` and ignores duplicates
    (only a warning, so ``nginx -t`` still passes) — a duplicated instance sharing a
    domain would silently be unreachable."""
    target = (domain or "").strip()
    if not target or not os.path.isdir(directory):
        return False
    for name in os.listdir(directory):
        real = os.path.realpath(os.path.join(directory, name))
        if not os.path.isfile(real):
            continue
        try:
            with open(real, encoding="utf-8", errors="replace") as file_handle:
                for raw_line in file_handle:
                    line = raw_line.strip()
                    if line.startswith("#") or not line.startswith("server_name"):
                        continue
                    if target in line.rstrip(";").split()[1:]:
                        return True
        except OSError:
            continue
    return False


def _filestore_copy_commands(
    source_config: InstanceConfig,
    source_db: str,
    target_config: InstanceConfig,
    target_db: str,
    overwrite: bool,
) -> list[Command]:
    """Copy the source filestore into the **target** instance's data dir, owned by
    the target user."""
    source_filestore = _filestore_path(source_config, source_db)
    target_filestore = _filestore_path(target_config, target_db)
    target_parent = target_filestore.rsplit("/", 1)[0]
    commands = [
        Command('Create the target filestore base path', f"mkdir -p {_quote(target_parent)}")
    ]
    if overwrite:
        commands.append(
            Command('Remove the previous target filestore', f"rm -rf {_quote(target_filestore)}")
        )
    commands.append(
        Command('Duplicate the filestore', f"cp -a {_quote(source_filestore)} {_quote(target_filestore)}")
    )
    commands.append(
        Command(
            'Own the target filestore',
            f"chown -R {_quote(target_config.odoo_user)}:{_quote(target_config.odoo_user)} {_quote(target_filestore)}",
        )
    )
    return commands


def _plan_refresh_target(
    source_config: InstanceConfig,
    target_config: InstanceConfig,
    source_db: str,
    target_db: str,
    method: str,
    migration_mode: str,
    neutralize: bool,
    duplicate_filestore: bool,
) -> list[Command]:
    """Refresh an existing target in place: keep its config/service, replace data."""
    existing = read_odoo_conf(target_config.odoo_conf_file)
    target_owner = existing.get("db_user", target_db)
    print(
        level_text(
            "INFO",
            tf('Target instance {} exists — refreshing it in place from {}.', target_config.instance, source_db),
        )
    )
    commands: list[Command] = [
        Command('Stop the target Odoo service', f"systemctl stop {_quote(target_config.odoo_service)} || true"),
    ]
    commands.extend(_drop_db_commands(target_db))
    commands.extend(_seed_db_commands(source_db, target_db, target_owner, method))
    commands.extend(_post_db_mode_commands(_psql_target_local(target_db), migration_mode, neutralize))
    if duplicate_filestore:
        commands.extend(
            _filestore_copy_commands(source_config, source_db, target_config, target_db, overwrite=True)
        )
    commands.append(
        Command('Start the target Odoo service', f"systemctl start {_quote(target_config.odoo_service)}")
    )
    return commands


def _plan_replica_target(
    source_config: InstanceConfig,
    creds: DbCredentials,
    target_config: InstanceConfig,
    source_db: str,
    target_db: str,
    method: str,
    migration_mode: str,
    neutralize: bool,
    duplicate_filestore: bool,
) -> list[Command] | None:
    """Provision a brand-new target instance seeded from the source."""
    if database_exists(target_db):
        print(level_text("ERROR", tf('Target DB already exists: {}', target_db)))
        return None

    branch = _detect_source_repo_branch(source_config)
    if branch:
        target_config.repo_branch = branch
        match = re.search(r"\d+", branch)
        if match:
            target_config.version = match.group(0)
    target_config.repo_branch = ask_text('Odoo repo branch (from source)', target_config.repo_branch, required=True)
    target_config.version = ask_text('Odoo version', target_config.version, required=True)

    suggested_http, suggested_gevent = _suggest_instance_ports(
        target_config.http_port, target_config.gevent_port
    )
    target_config.http_port = ask_int('Target internal HTTP port', suggested_http)
    target_config.gevent_port = ask_int('Target internal gevent port', suggested_gevent)
    target_config.db_host = creds.host
    target_config.db_port = creds.port

    # Same secrets + production-hardening prompts as a fresh install, so the operator
    # decides the secrets, list_db, dbfilter, workers and db_sslmode (not silent defaults).
    target_config.db_password = _prompt_secret('Target DB password', target_config.instance)
    target_config.odoo_admin_passwd = _prompt_secret(
        'Target Odoo admin_passwd (master password)', target_config.instance
    )
    target_config.ensure_strong_secrets()
    _prompt_production_hardening(target_config)

    # A replica that fronts Nginx MUST use a domain not already served by another
    # vhost: Nginx keeps the first server_name and ignores duplicates (only a
    # warning, so `nginx -t` still passes), which would make the replica unreachable.
    nginx_version = detect_nginx_version()
    nginx_mode = _choose_nginx_mode()
    if nginx_mode in {'Configure HTTP', 'Configure HTTPS'}:
        while True:
            target_config.domain = ask_text(
                'Target public domain (must differ from other instances)', target_config.domain, required=True
            )
            if not _nginx_server_name_in_use(target_config.domain):
                break
            print(
                level_text(
                    "WARN",
                    tf('The domain {} is already served by another Nginx vhost — the duplicated instance would be unreachable. Choose a different domain.', target_config.domain),
                )
            )
    else:
        target_config.domain = ask_text('Target public domain', target_config.domain, required=True)

    wkhtmltopdf_plan = _maybe_plan_wkhtmltopdf()

    print(
        level_text(
            "INFO",
            tf('Target instance {} does not exist — creating a replica seeded from {}.', target_config.instance, source_db),
        )
    )

    commands: list[Command] = []
    commands.extend(plan_ensure_db_role(target_config))
    commands.extend(_seed_db_commands(source_db, target_db, target_db, method))
    commands.extend(plan_odoo_base_setup(target_config, service_autostart=True, start_now=False))
    commands.extend(wkhtmltopdf_plan)
    if duplicate_filestore:
        commands.extend(
            _filestore_copy_commands(source_config, source_db, target_config, target_db, overwrite=False)
        )
    commands.extend(_post_db_mode_commands(_psql_target_local(target_db), migration_mode, neutralize))
    commands.append(
        Command('Start the target Odoo service', f"systemctl start {_quote(target_config.odoo_service)}")
    )
    if nginx_mode == 'Configure HTTP':
        commands.extend(plan_nginx_http(target_config, nginx_version))
    elif nginx_mode == 'Configure HTTPS':
        commands.extend(_maybe_plan_certs(target_config))
        commands.extend(plan_nginx_https(target_config, nginx_version))
    return commands


def _duplicate_database(
    config: InstanceConfig, cached: DbCredentials | None = None
) -> DbCredentials | None:
    """Duplicate a database only (no instance provisioning), reusing the same copy
    method and copied/moved + neutralize semantics as instance duplication."""
    creds = _ask_db_credentials(config.instance, cached)
    source_db = _pick_db_name(creds, 'Source DB to duplicate', required=True)
    if not source_db:
        print(level_text("INFO", 'No source DB, operation cancelled.'))
        return creds
    if not _is_local_db_host(creds.host):
        print(
            level_text(
                "WARN",
                'Database duplication requires a local PostgreSQL server (sudo -u postgres). For a remote DB, use Backup then Restore.',
            )
        )
        return creds

    target_db = ask_text('Target DB', "", required=True)
    if not _is_safe_db_name(source_db) or not _is_safe_db_name(target_db):
        print(
            level_text(
                "ERROR",
                'Unsafe database name (only letters, digits, and _ . - are allowed).',
            )
        )
        return creds
    if source_db == target_db:
        print(level_text("ERROR", 'Source and target databases must differ.'))
        return creds

    method_choice = choose(
        'Database copy method',
        [
            'Robust: pg_dump then restore (cross-user, recommended)',
            'Fast: template copy (same DB owner)',
        ],
        default_index=0,
    )
    if not method_choice:
        print(level_text("INFO", 'Operation cancelled.'))
        return creds
    method = "template" if method_choice.startswith('Fast') else "dump"

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

    overwrite = False
    if database_exists(target_db):
        overwrite = ask_bool(tf('The target DB {} exists — overwrite it?', target_db), False)
        if not overwrite:
            print(level_text("INFO", 'Operation cancelled.'))
            return creds

    existing = read_odoo_conf(config.odoo_conf_file)
    target_owner = existing.get("db_user") or config.db_user or config.instance

    commands: list[Command] = []
    if overwrite:
        commands.extend(_drop_db_commands(target_db))
    commands.extend(_seed_db_commands(source_db, target_db, target_owner, method))
    commands.extend(_post_db_mode_commands(_psql_target_local(target_db), migration_mode, neutralize))
    if duplicate_filestore:
        commands.extend(
            _filestore_copy_commands(config, source_db, config, target_db, overwrite=overwrite)
        )

    if not confirm_with_phrase(
        'Sensitive duplication action detected.',
        f"DUPLICAR {config.instance}",
    ):
        print(level_text("INFO", 'Invalid confirmation. Operation cancelled.'))
        return creds

    _execute_plan(commands)
    return creds


def _duplicate_instance(
    config: InstanceConfig, cached: DbCredentials | None = None
) -> DbCredentials | None:
    """Duplicate a source instance into a target: create a full replica when the
    target does not exist, or refresh an existing target in place from the source."""
    creds = _ask_db_credentials(config.instance, cached)
    source_db = _pick_db_name(creds, 'Source DB to duplicate', required=True)
    if not source_db:
        print(level_text("INFO", 'No source DB, operation cancelled.'))
        return creds

    if not _is_local_db_host(creds.host):
        print(
            level_text(
                "WARN",
                'Orchestrated duplication requires a local PostgreSQL server (sudo -u postgres). For a remote DB, use Backup then Restore.',
            )
        )
        return creds

    target_instance = ask_text('Target instance name', "", required=True)
    target_db = ask_text('Target DB', target_instance, required=True)

    if not _is_safe_db_name(source_db) or not _is_safe_db_name(target_db):
        print(
            level_text(
                "ERROR",
                'Unsafe database name (only letters, digits, and _ . - are allowed).',
            )
        )
        return creds

    target_config = InstanceConfig(instance=target_instance)
    target_config.db_user = target_db
    target_config.db_name = target_db
    try:
        target_config.validate_identifiers()
    except ValueError as error:
        print(level_text("ERROR", str(error)))
        return creds

    target_exists = (
        service_exists(target_instance)
        or path_exists(target_config.odoo_home)
        or path_exists(target_config.odoo_conf_file)
    )

    method_choice = choose(
        'Database copy method',
        [
            'Robust: pg_dump then restore (cross-user, recommended)',
            'Fast: template copy (same DB owner)',
        ],
        default_index=0,
    )
    if not method_choice:
        print(level_text("INFO", 'Operation cancelled.'))
        return creds
    method = "template" if method_choice.startswith('Fast') else "dump"

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

    if target_exists:
        commands = _plan_refresh_target(
            config, target_config, source_db, target_db, method, migration_mode, neutralize, duplicate_filestore
        )
    else:
        commands = _plan_replica_target(
            config, creds, target_config, source_db, target_db, method, migration_mode, neutralize, duplicate_filestore
        )
    if commands is None:
        return creds

    if not confirm_with_phrase(
        'Sensitive duplication action detected.',
        f"DUPLICAR {config.instance}",
    ):
        print(level_text("INFO", 'Invalid confirmation. Operation cancelled.'))
        return creds

    _execute_plan(commands)
    return creds
