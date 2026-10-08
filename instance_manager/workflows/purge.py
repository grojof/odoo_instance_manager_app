"""Total superuser purge of an instance (residues, databases, roles)."""

from __future__ import annotations

import os
import shlex
from dataclasses import dataclass

from ..i18n import t, tf
from ..models import POSTGRES_IDENTIFIER_RE, InstanceConfig, is_valid_db_name
from ..planners import _safe_token, _sql_literal, plan_remove_scheduled_backup
from ..prompts import (
    ask_int,
    ask_secret,
    ask_text,
    confirm_with_phrase,
)
from ..system import (
    Command,
    list_instances,
    path_exists,
    pg_env,
    read_odoo_conf,
    run,
    service_exists,
)
from ..ui import render_table, title
from .common import (
    _execute_plan,
    _odoo_conf_candidates,
    _quote,
    _resolve_data_dir,
    _select_existing_instance,
    _validate_instance_or_abort,
)


@dataclass(frozen=True)
class DbAdminSession:
    """An authenticated PostgreSQL admin session for the purge flow.

    ``mode`` is ``"local"`` (via ``sudo -u postgres``, no credentials) or
    ``"remote"`` (host/port/user/password).
    """

    mode: str
    db_host: str
    db_port: int
    admin_user: str
    admin_password: str


def _resolve_db_admin_access() -> DbAdminSession | None:
    db_host = ask_text('DB server for total removal', "127.0.0.1", required=True)
    db_port = ask_int('DB port', 5432)

    if db_host in {"127.0.0.1", "localhost", "::1"}:
        local_probe = run(
            'sudo -u postgres psql -d postgres -tAc "SELECT 1;"',
            check=False,
        )
        if local_probe.returncode == 0 and "1" in local_probe.stdout:
            print(t('[OK] Local PostgreSQL admin access detected (sudo -u postgres).'))
            return DbAdminSession("local", db_host, db_port, "", "")
        print(t('[WARN] Could not use sudo -u postgres on this server.'))

    print(t('[INFO] We will attempt an admin connection with username/password on the DB server.'))
    db_admin_user = ask_text('DB admin user', "postgres", required=True)
    db_admin_password = ask_secret('DB admin password')

    probe_cmd = (
        f"psql -X -h {_quote(db_host)} -p {int(db_port)} "
        f"-U {_quote(db_admin_user)} -d postgres -tAc 'SELECT 1;'"
    )
    probe = run(probe_cmd, check=False, env=pg_env(db_admin_password))
    if probe.returncode == 0 and "1" in probe.stdout:
        print(t('[OK] Remote admin connection validated.'))
        return DbAdminSession("remote", db_host, db_port, db_admin_user, db_admin_password)

    detail = probe.stderr.strip() or probe.stdout.strip() or 'no detail'
    print(tf('[ERROR] Could not connect to the DB server with admin credentials: {}', detail))
    print(
        t('[INFO] You must allow the connection to the PostgreSQL server and use a user with full privileges (superuser/admin).')
    )
    return None


def _db_admin_psql_command(session: DbAdminSession, sql: str, psql_flags: str = "") -> str:
    flags = f"{psql_flags} " if psql_flags else ""
    if session.mode == "local":
        return f"sudo -u postgres psql -v ON_ERROR_STOP=1 -d postgres {flags}-c {shlex.quote(sql)}"

    return (
        f"psql -X -v ON_ERROR_STOP=1 "
        f"-h {_quote(session.db_host)} -p {int(session.db_port)} "
        f"-U {_quote(session.admin_user)} -d postgres {flags}-c {shlex.quote(sql)}"
    )


def _admin_env(session: DbAdminSession) -> dict[str, str]:
    """The admin password for a remote session, in the environment only."""
    return pg_env(session.admin_password) if session.mode == "remote" else {}


def _db_admin_dropdb_command(session: DbAdminSession, db_name: str) -> str:
    if session.mode == "local":
        # --force (PostgreSQL 13+) closes the sessions and refuses new ones in the
        # same statement; a remote server may be older, so it keeps the terminate.
        return f"sudo -u postgres dropdb --if-exists --force {_quote(db_name)}"

    return (
        "dropdb --if-exists "
        f"-h {_quote(session.db_host)} -p {int(session.db_port)} "
        f"-U {_quote(session.admin_user)} {_quote(db_name)}"
    )


def _like_prefix(value: str) -> str:
    """``value`` as a LIKE prefix pattern with its own ``_``/``%``/``\\`` escaped."""
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"{escaped}%"


def _instance_databases_sql(instance: str, db_user: str, by_owner: bool = True) -> str:
    """The instance's databases: owned by its role, or named exactly like it. A name
    prefix is not enough — purging ``shop`` must not drop ``shop2`` or ``shop_eu``.
    ``by_owner`` is off when another instance uses the same role."""
    owner = f" OR r.rolname = '{_sql_literal(db_user or instance)}'" if by_owner else ""
    return (
        "SELECT d.datname "
        "FROM pg_database d JOIN pg_roles r ON d.datdba = r.oid "
        "WHERE d.datistemplate = false "
        f"AND (d.datname = '{_sql_literal(instance)}'{owner}) "
        "ORDER BY d.datname;"
    )


def _instances_sharing_role(instance: str, db_user: str) -> list[str]:
    """Other instances whose ``odoo.conf`` connects as ``db_user``."""
    sharing = []
    for other in list_instances(InstanceConfig.base_instances_dir):
        if other == instance:
            continue
        for conf_path in _odoo_conf_candidates(other):
            values = read_odoo_conf(conf_path)
            if values:
                if values.get("db_user", "").strip() == db_user:
                    sharing.append(other)
                break
    return sharing


def _prefix_only_databases_sql(instance: str, db_user: str) -> str:
    """Databases whose name merely starts with the instance name and that the
    instance's role does not own: shown to the operator, never selected."""
    return (
        "SELECT d.datname "
        "FROM pg_database d JOIN pg_roles r ON d.datdba = r.oid "
        "WHERE d.datistemplate = false "
        f"AND d.datname LIKE '{_sql_literal(_like_prefix(instance))}' "
        f"AND d.datname <> '{_sql_literal(instance)}' "
        f"AND r.rolname <> '{_sql_literal(db_user or instance)}' "
        "ORDER BY d.datname;"
    )


def _query_names(session: DbAdminSession, sql: str) -> tuple[list[str], str | None]:
    query_cmd = _db_admin_psql_command(session, sql, psql_flags="-tA")
    result = run(query_cmd, check=False, env=_admin_env(session))
    if result.returncode != 0:
        error_text = result.stderr.strip() or result.stdout.strip() or "Unknown error"
        return [], error_text

    rows = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return rows, None


def _list_instance_databases(
    instance: str,
    session: DbAdminSession,
    db_user: str = "",
    by_owner: bool = True,
) -> tuple[list[str], str | None]:
    return _query_names(session, _instance_databases_sql(instance, db_user, by_owner))


def _list_filestore_databases(config: InstanceConfig) -> tuple[list[str], str]:
    filestore_root = f"{_resolve_data_dir(config)}/filestore"
    if not os.path.isdir(filestore_root):
        return [], filestore_root

    db_names = sorted(
        [
            entry
            for entry in os.listdir(filestore_root)
            if os.path.isdir(os.path.join(filestore_root, entry)) and not entry.startswith(".")
        ]
    )
    return db_names, filestore_root


def purge_instance_superuser() -> None:
    instance = _select_existing_instance()
    if not instance:
        print(t('[INFO] Operation cancelled.'))
        return

    config = _validate_instance_or_abort(instance)
    if config is None:
        return

    filestore_dbs, filestore_root = _list_filestore_databases(config)

    db_user = ask_text(
        'Instance DB user (to find associated databases)',
        instance,
        required=True,
        validate=lambda value: None
        if POSTGRES_IDENTIFIER_RE.fullmatch(value)
        else 'invalid db_user for PostgreSQL. Use the format: start with [a-z_] and only [a-z0-9_] (max 63).',
    )

    sharing = _instances_sharing_role(instance, db_user)
    if sharing:
        print(tf(
            "[WARN] Role {} is also used by: {}. Its databases are not selected by owner and the role is not dropped.",
            db_user, ", ".join(sharing),
        ))

    session = _resolve_db_admin_access()
    db_names: list[str] = list(filestore_dbs)
    dbs_by_prefix: list[str] = []
    db_error: str | None = None
    if session:
        dbs_by_prefix, db_error = _list_instance_databases(
            instance, session, db_user, by_owner=not sharing
        )
        if db_error:
            print(tf("[WARN] Could not detect the databases of '{}': {}", instance, db_error))
        for db_name in dbs_by_prefix:
            if db_name not in db_names:
                db_names.append(db_name)
        others, _error = _query_names(session, _prefix_only_databases_sql(instance, db_user))
        if others:
            print(tf(
                "[INFO] Not selected — their name starts with '{}' but role {} does not own them: {}. Add any that belong to this instance below.",
                instance, db_user, ", ".join(others),
            ))
    else:
        print(
            t('[WARN] Local cleanup will continue (service/config/store). DB/role deletion is skipped due to a missing admin connection to the DB server.')
        )

    manual_dbs = ask_text(
        'Extra DBs to delete (comma-separated, optional)',
        "",
        required=False,
    )
    if manual_dbs:
        for item in [name.strip() for name in manual_dbs.split(",") if name.strip()]:
            if not is_valid_db_name(item):
                print(tf('[ERROR] Invalid database name, ignored: {}', item))
                continue
            if item not in db_names:
                db_names.append(item)
    # Filestore folders are directory names, not checked database names.
    db_names = [name for name in db_names if is_valid_db_name(name)]

    if db_names:
        print(t('\nCandidate databases for deletion:'))
        for name in db_names:
            print(f"- {name}")
    else:
        print(t('[INFO] No databases detected/specified for deletion.'))

    commands: list[Command] = [
        Command(
            'Stop the Odoo service',
            f"systemctl stop {_quote(config.odoo_service)} || true",
        ),
        Command(
            'Disable the Odoo service',
            f"systemctl disable {_quote(config.odoo_service)} || true",
        ),
        Command(
            'Remove unit file',
            f"rm -f {_quote(f'/etc/systemd/system/{config.odoo_service}.service')}",
        ),
        Command('Reload systemd', "systemctl daemon-reload"),
        *plan_remove_scheduled_backup(config),
        Command(
            'Remove Odoo configuration', f"rm -rf {_quote(config.odoo_conf_dir)}"
        ),
        Command('Remove instance home', f"rm -rf {_quote(config.odoo_home)}"),
        Command(
            'Remove the instance Linux user',
            f"id -u {_quote(config.odoo_user)} >/dev/null 2>&1 && userdel -r {_quote(config.odoo_user)} || true",
        ),
        Command(
            'Remove the instance Odoo/Nginx logs',
            f"rm -f {_quote(f'/var/log/odoo/{config.instance}.log')} {_quote(f'/var/log/nginx/{config.instance}.access.log')} {_quote(f'/var/log/nginx/{config.instance}.error.log')}",
        ),
        Command(
            'Remove Nginx HTTP',
            f"rm -f {_quote(f'/etc/nginx/sites-available/{config.nginx_http_name}')} {_quote(f'/etc/nginx/sites-enabled/{config.nginx_http_name}')}",
        ),
        Command(
            'Remove Nginx HTTPS',
            f"rm -f {_quote(f'/etc/nginx/sites-available/{config.nginx_https_name}')} {_quote(f'/etc/nginx/sites-enabled/{config.nginx_https_name}')}",
        ),
        Command('Remove instance SSL', f"rm -rf {_quote(config.nginx_ssl_dir)}"),
        # Its log is removed above: fail2ban refuses to start with a jail whose log
        # file is missing, and would take the sshd jail down with it.
        Command(
            'Remove the instance fail2ban jail',
            f"rm -f {_quote(f'/etc/fail2ban/jail.d/odoo-auth-{_safe_token(config.instance)}.local')} && "
            "{ ! systemctl is-active --quiet fail2ban || systemctl reload fail2ban; }",
        ),
        Command('Remove the instance filestore root', f"rm -rf {_quote(filestore_root)}"),
        Command('Validate/reload Nginx (best effort)', "nginx -t && systemctl reload nginx || true"),
    ]

    if session:
        for db_name in db_names:
            db_literal = _sql_literal(db_name)
            terminate_sql = (
                "SELECT pg_terminate_backend(pid) "
                "FROM pg_stat_activity "
                f"WHERE datname = '{db_literal}' AND pid <> pg_backend_pid();"
            )
            commands.append(
                Command(
                    tf('Close active connections of DB {}', db_name),
                    _db_admin_psql_command(session, terminate_sql) + " || true",
                    env=_admin_env(session),
                )
            )
            commands.append(
                Command(
                    tf('Delete DB {}', db_name),
                    _db_admin_dropdb_command(session, db_name),
                    env=_admin_env(session),
                )
            )

        role_candidates = [] if sharing else [db_user]
        if config.instance not in _instances_sharing_role(instance, config.instance):
            role_candidates.append(config.instance)
        unique_roles: list[str] = []
        for role in role_candidates:
            if role and role not in unique_roles:
                unique_roles.append(role)

        for role in unique_roles:
            drop_role_sql = f"DROP ROLE IF EXISTS {role};"
            commands.append(
                Command(
                    tf('Delete PostgreSQL role {} (if it exists)', role),
                    _db_admin_psql_command(session, drop_role_sql) + " || true",
                    env=_admin_env(session),
                )
            )

    print(f"\n{title('Total-removal summary')}")
    summary_rows = [
        ['Instance', instance],
        ['systemd service detected', "yes" if service_exists(config.odoo_service) else "no"],
        ['Instance home detected', "yes" if path_exists(config.odoo_home) else "no"],
        ['Configuration detected', "yes" if path_exists(config.odoo_conf_dir) else "no"],
        ['Nginx HTTP detected', "yes" if path_exists(f"/etc/nginx/sites-available/{config.nginx_http_name}") else "no"],
        ['Nginx HTTPS detected', "yes" if path_exists(f"/etc/nginx/sites-available/{config.nginx_https_name}") else "no"],
        ['SSL detected', "yes" if path_exists(config.nginx_ssl_dir) else "no"],
        ['Filestore root detected', f"{'yes' if path_exists(filestore_root) else 'no'} ({filestore_root})"],
        ['DBs by filestore', ", ".join(filestore_dbs) if filestore_dbs else '(none)'],
        ['DBs by owner/name', ", ".join(dbs_by_prefix) if dbs_by_prefix else '(none)'],
        ['DB admin access', session.mode if session else 'unavailable (local cleanup only)'],
        ['DBs to remove', ", ".join(db_names) if db_names else '(none detected)'],
        ['Commands to run', str(len(commands))],
    ]
    print(render_table(['Field', 'Value'], summary_rows))

    if not confirm_with_phrase(
        'SUPER destructive action detected.',
        f"DELETE-ALL {instance}",
    ):
        print(t('[INFO] Invalid confirmation. Operation cancelled.'))
        return

    _execute_plan(commands)
