"""Backup, restore, and duplicate instance data (database + filestore)."""

from __future__ import annotations

import datetime
import os
import re

from .. import neutralise
from ..i18n import t, tf
from ..models import (
    POSTGRES_IDENTIFIER_RE,
    InstanceConfig,
    branch_error,
    domain_error,
    is_valid_db_name,
)
from ..planners import (
    BACKUP_DUMP_SUFFIX,
    BACKUP_FILESTORE_SUFFIX,
    _is_local_db_host,
    backup_basename,
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
    database_owner,
    detect_nginx_version,
    path_exists,
    read_odoo_conf,
    run,
    service_active,
    service_exists,
)
from ..ui import level_text, render_table
from .common import (
    DbCredentials,
    _ask_db_credentials,
    _execute_plan,
    _filestore_path,
    _pick_db_name,
    _quote,
    _resolve_data_dir,
)
from .install import (
    _choose_nginx_mode,
    _maybe_plan_certs,
    _maybe_plan_wkhtmltopdf,
    _plan_runtime,
    _prompt_production_hardening,
    _prompt_secret,
    _suggest_instance_ports,
    _supported_version_error,
)

_INVALID_DB_NAME = (
    "Invalid database name. Use letters, digits, '_', '.' and '-' (2-63 characters, "
    "starting with a letter or digit)."
)


def _is_safe_db_name(name: str) -> bool:
    """A database name Odoo accepts, and therefore safe in SQL identifiers and
    literals, in shell words and as a filestore path component."""
    return is_valid_db_name(name)


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


def _config_with_port(config: InstanceConfig, conf: dict[str, str]) -> InstanceConfig:
    """``config`` with the HTTP port its ``odoo.conf`` states, when it states one."""
    port = conf.get("http_port", "").strip()
    if port.isdigit():
        config.http_port = int(port)
    return config


def _local_url(config: InstanceConfig) -> str:
    """Where a neutralised copy's links point until an administrator logs in through
    its own domain (Odoo then rewrites ``web.base.url``): the target's own port."""
    return f"http://127.0.0.1:{config.http_port}"


def _post_db_mode_commands(
    psql_target: str,
    migration_mode: str,
    neutralize: bool,
    local_url: str,
) -> list[Command]:
    """Apply Odoo migration semantics to an already-restored target database.

    ``psql_target`` is a psql invocation already pointed at the target DB (built by
    :func:`_psql_target` or :func:`_psql_target_local`), so the same logic serves
    both the credential-based restore and the local, superuser-driven duplication.
    Each step is one statement that stops the plan when it fails: a copy left
    half-neutralised must not be handed to a running Odoo.
    """
    psql = f"{psql_target} -X -q -v ON_ERROR_STOP=1 -c"
    commands: list[Command] = []
    if migration_mode == 'Copied (new UUID on target)':
        commands.append(
            Command(
                'Give the copy its own identity: new database.uuid, database.secret, create date',
                f"{psql} {_quote(neutralise.copied_identity_sql())}",
            )
        )
    if neutralize:
        commands += [
            Command(
                'Neutralise the copy (crons, mail, payment, EDI/SII, calendars, webhooks, IAP, base URL)',
                f"{psql} {_quote(neutralise.apply_sql(local_url))}",
            ),
            Command(
                'Check nothing in the copy can still act on the outside',
                f"{psql} {_quote(neutralise.guard_sql(local_url))}",
            ),
        ]
    return commands


def _hand_over_commands(target_db: str, target_owner: str) -> list[Command]:
    """Give the seeded database to its role. Until now postgres owned it, and an
    Odoo lists only the databases its own role owns (``list_dbs``: ``datdba`` is
    the connected role) — so no cron worker could start on the copy before it was
    neutralised. Names MUST be safe (:func:`_is_safe_db_name`)."""
    return [
        Command(
            tf('Hand the database over to role {}', target_owner),
            "sudo -u postgres psql -X -q -d postgres -v ON_ERROR_STOP=1 -c "
            f"{_quote(f'ALTER DATABASE "{target_db}" OWNER TO "{target_owner}";')}",
        )
    ]


def _lock_db_access_commands(db_name: str, owner: str) -> list[Command]:
    """Restrict a database to its owner: revoke ``CONNECT`` from ``PUBLIC`` and grant
    it to the owning role, so an Odoo role cannot reach **other** instances'
    databases. Names MUST be safe (:func:`_is_safe_db_name`)."""
    psql = "sudo -u postgres psql -d postgres -v ON_ERROR_STOP=1"
    return [
        Command(
            'Restrict DB access to its owner (revoke PUBLIC connect)',
            f'{psql} -c \'REVOKE CONNECT ON DATABASE "{db_name}" FROM PUBLIC;\'',
        ),
        Command(
            'Grant DB connect to the owner role',
            f'{psql} -c \'GRANT CONNECT ON DATABASE "{db_name}" TO "{owner}";\'',
        ),
    ]


def _template_copy_script(source_db: str, target_db: str) -> str:
    """``createdb -T`` needs no other session on the template, and a running Odoo
    reconnects at once: so new connections to the source are refused first, its
    sessions terminated, the copy made, and — through a ``trap … EXIT`` — the source
    opened again whatever happened. Names MUST be safe (:func:`_is_safe_db_name`)."""
    psql = "sudo -u postgres psql -X -q -v ON_ERROR_STOP=1 -d postgres"
    return "\n".join(
        [
            "set -e",
            f"reopen() {{ {psql} -c 'ALTER DATABASE \"{source_db}\" WITH ALLOW_CONNECTIONS true;' >/dev/null 2>&1 || true; }}",
            "trap reopen EXIT",
            f"{psql} -c 'ALTER DATABASE \"{source_db}\" WITH ALLOW_CONNECTIONS false;'",
            f"{psql} -c \"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{source_db}' AND pid <> pg_backend_pid();\" >/dev/null",
            f"sudo -u postgres createdb -T {_quote(source_db)} {_quote(target_db)}",
        ]
    )


def _seed_db_commands(source_db: str, target_db: str, target_owner: str, method: str) -> list[Command]:
    """Seed ``target_db`` from ``source_db`` on the **local** server (via
    ``sudo -u postgres``) and lock its access down to ``target_owner``. The database
    stays owned by postgres — invisible to every Odoo — until
    :func:`_hand_over_commands`, which callers run after the migration semantics.

    ``method="template"`` frees the source of sessions and does a fast template copy
    (correct when the target keeps the source's owner). ``method="dump"`` restores a
    ``pg_dump`` with ``--role`` so every object is re-owned by ``target_owner`` —
    correct for a cross-user target (production→development). Names MUST be safe
    (:func:`_is_safe_db_name`)."""
    if method == "template":
        commands = [
            Command(
                'Seed target DB via template copy (source closed to new sessions meanwhile)',
                _template_copy_script(source_db, target_db),
            ),
        ]
    else:
        commands = [
            Command(
                'Create the empty target DB (owned by postgres until it is handed over)',
                f"sudo -u postgres createdb {_quote(target_db)}",
            ),
            # The restore runs as the target role while postgres still owns the
            # database: from PostgreSQL 15 only the owner may create in `public`, and a
            # trusted extension (Odoo 18 creates pg_trgm) needs CREATE on the database.
            # Handing the database over later makes the role its owner anyway.
            Command(
                tf('Let role {} create in the new DB until it is handed over', target_owner),
                f"sudo -u postgres psql -X -q -v ON_ERROR_STOP=1 -d {_quote(target_db)} -c "
                + _quote(
                    f'GRANT CREATE ON DATABASE "{target_db}" TO "{target_owner}"; '
                    f'GRANT ALL ON SCHEMA public TO "{target_owner}";'
                ),
            ),
            Command(
                'Seed target DB via pg_dump | pg_restore (re-owned by the target role)',
                "set -o pipefail; "
                f"sudo -u postgres pg_dump -Fc {_quote(source_db)} | "
                f"sudo -u postgres pg_restore -d {_quote(target_db)} --no-owner --role={_quote(target_owner)} --no-privileges",
            ),
        ]
    commands.extend(_lock_db_access_commands(target_db, target_owner))
    return commands


def _drop_db_commands(target_db: str) -> list[Command]:
    """Drop ``target_db`` on the local server (superuser). ``--force`` (PostgreSQL
    13+, older than every supported distribution's server) terminates its sessions
    and refuses new ones in the same statement, so a client reconnecting between a
    terminate and the drop cannot make it fail halfway through a plan."""
    return [
        Command(
            'Drop the target DB (if it exists), closing its sessions',
            f"sudo -u postgres dropdb --if-exists --force {_quote(target_db)}",
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
    if not _is_safe_db_name(db_name):
        print(level_text("ERROR", _INVALID_DB_NAME))
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
    base = f"{backup_dir}/{backup_basename(config.instance, db_name, ts)}"
    dump_path = base + BACKUP_DUMP_SUFFIX
    archive_path = base + BACKUP_FILESTORE_SUFFIX
    # A dump holds password hashes, API keys and mail/payment secrets: the directory
    # and every file in it are private to root.
    commands: list[Command] = [
        Command(
            'Create the private backup directory',
            f"install -d -m 700 {quoted_backup_dir} && chmod 700 {quoted_backup_dir}",
        )
    ]

    if backup_mode in {'Database only', 'Database + Filestore'}:
        commands.append(
            Command(
                'Export DB backup (custom format, atomic)',
                f"umask 077 && TMP={_quote(dump_path + '.partial')} && "
                f"PGPASSWORD={_quote(db_password)} pg_dump -h {_quote(db_host)} -p {db_port} -U {_quote(db_user)} -Fc -f \"$TMP\" {_quote(db_name)} && "
                f"mv \"$TMP\" {_quote(dump_path)} || {{ rm -f \"$TMP\"; exit 1; }}",
            )
        )

    if backup_mode in {'Filestore only', 'Database + Filestore'}:
        commands.append(
            Command(
                'Export filestore backup (atomic)',
                f"umask 077 && TMP={_quote(archive_path + '.partial')} && "
                f"test -d {_quote(filestore_dir)} && "
                # GNU tar exits 1 when a file changed while read (Odoo keeps
                # writing attachments); anything above 1 is a real failure.
                f"{{ tar --warning=no-file-changed -czf \"$TMP\" -C {_quote(filestore_dir)} . || [ $? -eq 1 ]; }} && "
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
    if not _is_safe_db_name(target_db):
        print(level_text("ERROR", _INVALID_DB_NAME))
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
        # The instance's own role owns what it creates, so its cron worker would see
        # the copy as soon as it exists: the service waits until it is neutralised.
        stop_service = neutralize and service_active(config.odoo_service)
        if stop_service:
            commands.append(
                Command(
                    'Stop the Odoo service while the copy is restored and neutralised',
                    f"systemctl stop {_quote(config.odoo_service)}",
                )
            )
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
                _local_url(_config_with_port(config, read_odoo_conf(config.odoo_conf_file))),
            )
        )
        if stop_service:
            commands.append(
                Command('Start the Odoo service again', f"systemctl start {_quote(config.odoo_service)}")
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

        if overwrite_store:
            # Moved aside, not deleted: attachments created after the archive was
            # taken are still referenced by the database.
            kept = f"{target_filestore}.replaced-{datetime.datetime.now():%Y%m%d_%H%M%S}"
            commands.append(
                Command(
                    tf('Move the previous filestore aside to {}', kept),
                    f"mv -- {_quote(target_filestore)} {_quote(kept)}",
                )
            )
        commands.append(
            Command(
                'Create the filestore base path', f"mkdir -p {_quote(target_filestore)}"
            )
        )
        commands.append(
            Command(
                'Restore the filestore into the target',
                f"tar --no-same-owner -xzf {_quote(filestore_backup)} -C {_quote(target_filestore)}",
            )
        )
        commands.append(
            Command(
                'Own the data dir by the instance user (filestore, sessions, …)',
                f"chown -R {_quote(config.odoo_user)}:{_quote(config.odoo_user)} "
                f"{_quote(_resolve_data_dir(config))}",
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


def _detect_source_core(config: InstanceConfig) -> str:
    """``ocb`` when the source checkout's origin is OCA's OCB, else ``odoo``, so a
    replica runs the same core."""
    result = run(
        f"git -C {_quote(config.odoo_home + '/odoo')} remote get-url origin 2>/dev/null",
        check=False,
    )
    return "ocb" if "/oca/ocb" in result.stdout.strip().lower() else "odoo"


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
    """Copy the source filestore into the **target** instance's data dir, then hand
    the **whole data dir** to the target user.

    ``mkdir``/``cp`` run as root, so the created ``.local/share/Odoo`` tree would be
    root-owned and Odoo (running as the target user) could not create its
    ``sessions``/``filestore`` entries. Chowning the entire resolved data dir fixes
    that, not just the copied filestore subdirectory."""
    source_filestore = _filestore_path(source_config, source_db)
    target_filestore = _filestore_path(target_config, target_db)
    target_parent = target_filestore.rsplit("/", 1)[0]
    target_data_dir = _resolve_data_dir(target_config)
    owner = f"{_quote(target_config.odoo_user)}:{_quote(target_config.odoo_user)}"
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
            'Own the target data dir (filestore, sessions, …)',
            f"chown -R {owner} {_quote(target_data_dir)}",
        )
    )
    return commands


def _replicate_venv_packages_command(
    source_config: InstanceConfig, target_config: InstanceConfig
) -> Command:
    """Install the source venv's Python packages into the target venv, so addon
    dependencies the source installed beyond ``requirements.txt`` are present in the
    replica. The root shell captures a filtered ``pip freeze`` of the source (only
    ``name==version`` lines, dropping editable/URL entries) and installs it into the
    target as the target user."""
    source_pip = f"{source_config.odoo_home}/venv/bin/pip"
    target_pip = f"{target_config.odoo_home}/venv/bin/pip"
    reqs = f"/tmp/{target_config.instance}_venv_reqs.txt"
    script = (
        f"sudo -u {_quote(source_config.odoo_user)} {_quote(source_pip)} freeze 2>/dev/null "
        f"| grep -E '^[A-Za-z0-9_.-]+==' > {_quote(reqs)} || true; "
        f"if [ -s {_quote(reqs)} ]; then "
        f"sudo -u {_quote(target_config.odoo_user)} {_quote(target_pip)} install -r {_quote(reqs)}; "
        f"fi; rm -f {_quote(reqs)}"
    )
    return Command('Replicate the source venv Python packages', script)


def _template_owner_error(source_db: str, target_owner: str) -> str | None:
    """Why a template copy cannot seed a database for ``target_owner``, or None.

    A template copy keeps every table owned by the source's role; only the database
    itself gets the new owner. A target role other than the source's would find no
    privilege on any table."""
    source_owner = database_owner(source_db)
    if source_owner is None or source_owner == target_owner:
        return None
    return tf(
        'The template copy keeps the source owner ({}) on every table, so the target role {} could not use them. Choose the pg_dump copy.',
        source_owner,
        target_owner,
    )


def _existing_target_error(target_db: str, target_owner: str) -> str | None:
    """Why an existing ``target_db`` must not be dropped for ``target_owner``, or None
    (it does not exist, or it already belongs to that role)."""
    owner = database_owner(target_db)
    if owner is None or owner == target_owner:
        return None
    return tf(
        'The database {} belongs to role {}, not to the target role {}: it is not the target\'s database and will not be dropped.',
        target_db,
        owner,
        target_owner,
    )


def _plan_refresh_target(
    source_config: InstanceConfig,
    target_config: InstanceConfig,
    source_db: str,
    target_db: str,
    method: str,
    migration_mode: str,
    neutralize: bool,
    duplicate_filestore: bool,
) -> list[Command] | None:
    """Refresh an existing target in place: keep its config/service, replace data.

    The target's database is dropped only when it belongs to the target's own role
    and the operator says so: the target name is typed, and a slip must not drop
    production."""
    existing = read_odoo_conf(target_config.odoo_conf_file)
    target_owner = existing.get("db_user") or target_config.db_user
    if not POSTGRES_IDENTIFIER_RE.fullmatch(target_owner):
        print(level_text("ERROR", tf('Invalid db_user in {}: {}', target_config.odoo_conf_file, target_owner)))
        return None
    error = _existing_target_error(target_db, target_owner)
    if error is None and method == "template":
        error = _template_owner_error(source_db, target_owner)
    if error:
        print(level_text("ERROR", error))
        return None
    if database_exists(target_db) and not ask_bool(
        tf('The target DB {} exists and will be dropped and replaced by a copy of {}. Continue?', target_db, source_db),
        False,
    ):
        print(level_text("INFO", 'Operation cancelled.'))
        return None
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
    commands.extend(_post_db_mode_commands(
        _psql_target_local(target_db), migration_mode, neutralize,
        _local_url(_config_with_port(target_config, existing)),
    ))
    commands.extend(_hand_over_commands(target_db, target_owner))
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
    # The replica's database belongs to its own new role, never the source's.
    if method == "template":
        print(level_text("ERROR", _template_owner_error(source_db, target_db) or tf(
            'A new instance gets its own role ({}); the template copy would leave every table owned by the source role. Choose the pg_dump copy.',
            target_db,
        )))
        return None

    branch = _detect_source_repo_branch(source_config)
    if branch:
        target_config.repo_branch = branch
        match = re.search(r"\d+", branch)
        if match:
            target_config.version = match.group(0)
    target_config.repo_branch = ask_text(
        'Odoo repo branch (from source)', target_config.repo_branch, required=True, validate=branch_error
    )
    target_config.version = ask_text(
        'Odoo version', target_config.version, required=True, validate=_supported_version_error
    )
    target_config.core = _detect_source_core(source_config)
    target_config.data_dir = target_config.managed_data_dir

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
                'Target public domain (must differ from other instances)', target_config.domain, required=True,
                validate=domain_error,
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
        target_config.domain = ask_text(
            'Target public domain', target_config.domain, required=True, validate=domain_error
        )

    wkhtmltopdf_plan = _maybe_plan_wkhtmltopdf()
    replicate_packages = ask_bool(
        "Replicate the source instance's extra Python packages into the target venv (recommended)?", True
    )

    print(
        level_text(
            "INFO",
            tf('Target instance {} does not exist — creating a replica seeded from {}.', target_config.instance, source_db),
        )
    )

    commands: list[Command] = []
    commands.extend(_plan_runtime(target_config))
    commands.extend(plan_ensure_db_role(target_config))
    commands.extend(_seed_db_commands(source_db, target_db, target_db, method))
    commands.extend(plan_odoo_base_setup(target_config, service_autostart=True, start_now=False))
    commands.extend(wkhtmltopdf_plan)
    if replicate_packages:
        commands.append(_replicate_venv_packages_command(source_config, target_config))
    if duplicate_filestore:
        commands.extend(
            _filestore_copy_commands(source_config, source_db, target_config, target_db, overwrite=False)
        )
    commands.extend(_post_db_mode_commands(
        _psql_target_local(target_db), migration_mode, neutralize, _local_url(target_config)
    ))
    commands.extend(_hand_over_commands(target_db, target_db))
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
        print(level_text("ERROR", _INVALID_DB_NAME))
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

    existing = read_odoo_conf(config.odoo_conf_file)
    target_owner = existing.get("db_user") or config.db_user or config.instance
    if not POSTGRES_IDENTIFIER_RE.fullmatch(target_owner):
        print(level_text("ERROR", tf('Invalid db_user in {}: {}', config.odoo_conf_file, target_owner)))
        return creds
    error = _existing_target_error(target_db, target_owner)
    if error is None and method == "template":
        error = _template_owner_error(source_db, target_owner)
    if error:
        print(level_text("ERROR", error))
        return creds

    overwrite = False
    if database_exists(target_db):
        overwrite = ask_bool(tf('The target DB {} exists — overwrite it?', target_db), False)
        if not overwrite:
            print(level_text("INFO", 'Operation cancelled.'))
            return creds

    commands: list[Command] = []
    if overwrite:
        commands.extend(_drop_db_commands(target_db))
    commands.extend(_seed_db_commands(source_db, target_db, target_owner, method))
    commands.extend(_post_db_mode_commands(
        _psql_target_local(target_db), migration_mode, neutralize,
        _local_url(_config_with_port(config, existing)),
    ))
    commands.extend(_hand_over_commands(target_db, target_owner))
    if duplicate_filestore:
        commands.extend(
            _filestore_copy_commands(config, source_db, config, target_db, overwrite=overwrite)
        )

    if not confirm_with_phrase(
        'Sensitive duplication action detected.',
        f"DUPLICATE {config.instance}",
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
    if target_instance == config.instance:
        print(level_text("ERROR", 'The target instance must differ from the source instance.'))
        return creds
    target_db = ask_text('Target DB', target_instance, required=True)

    if not _is_safe_db_name(source_db) or not _is_safe_db_name(target_db):
        print(level_text("ERROR", _INVALID_DB_NAME))
        return creds
    if source_db == target_db:
        print(level_text("ERROR", 'Source and target databases must differ.'))
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
        f"DUPLICATE {config.instance}",
    ):
        print(level_text("INFO", 'Invalid confirmation. Operation cancelled.'))
        return creds

    _execute_plan(commands)
    return creds


def _check_neutralisation(
    config: InstanceConfig, cached: DbCredentials | None = None
) -> DbCredentials | None:
    """Read-only: list what in a database can still act on the outside (the same
    rules the neutralisation applies) and whether the mail sink is in place. A module
    update switches non-``noupdate`` crons back on, so a copy is worth re-checking."""
    creds = _ask_db_credentials(config.instance, cached)
    db_name = _pick_db_name(creds, 'Database to check', required=True)
    if not db_name or not _is_safe_db_name(db_name):
        print(level_text("ERROR", _INVALID_DB_NAME))
        return creds
    psql = f"{_psql_target(creds.host, creds.port, creds.user, creds.password, db_name)} -X -tA -F '|' -c"
    found = run(f"{psql} {_quote(neutralise.columns_sql())}", check=False)
    if found.returncode != 0:
        print(level_text("ERROR", found.stderr.strip() or 'Could not read the database.'))
        return creds
    existing = {tuple(line.split("|", 1)) for line in found.stdout.splitlines() if "|" in line}
    rules = neutralise.applicable(existing)  # type: ignore[arg-type]
    url = _local_url(_config_with_port(config, read_odoo_conf(config.odoo_conf_file)))
    armed = run(f"{psql} {_quote(neutralise.check_sql(rules, url))}", check=False)
    rows = [line.split("|", 2) for line in armed.stdout.splitlines() if line.count("|") >= 2]
    sink = run(
        f"{psql} "
        + _quote(
            "SELECT count(*) FROM ir_mail_server WHERE active AND name = "
            f"'{neutralise.MAIL_SINK_NAME}' AND smtp_host = '{neutralise.MAIL_SINK_HOST}'"
        ),
        check=False,
    )
    if sink.stdout.strip() != "1":
        rows.append(["mail-sink", "0", t('missing: mail can leave through odoo.conf\'s smtp_server')])
    if armed.returncode != 0:
        print(level_text("ERROR", armed.stderr.strip() or 'Could not read the database.'))
        return creds
    if not rows:
        print(level_text("OK", tf('{}: nothing found that can act on the outside.', db_name)))
        return creds
    print(level_text("WARN", tf('{}: still able to act on the outside:', db_name)))
    print(render_table(['Rule', 'Rows', 'Examples'], rows))
    return creds

