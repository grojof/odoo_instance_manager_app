"""Total superuser purge of an instance (residues, databases, roles)."""

from __future__ import annotations

import os
import shlex
from dataclasses import dataclass

from ..models import InstanceConfig
from ..planners import _sql_literal
from ..prompts import (
    ask_int,
    ask_secret,
    ask_text,
    confirm_with_phrase,
)
from ..system import (
    Command,
    path_exists,
    run,
    service_exists,
)
from ..ui import render_table, title
from .common import (
    _execute_plan,
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
    db_host = ask_text("DB server para eliminación total", "127.0.0.1", required=True)
    db_port = ask_int("DB port", 5432)

    if db_host in {"127.0.0.1", "localhost", "::1"}:
        local_probe = run(
            'sudo -u postgres psql -d postgres -tAc "SELECT 1;"',
            check=False,
        )
        if local_probe.returncode == 0 and "1" in local_probe.stdout:
            print("[OK] Acceso admin local a PostgreSQL detectado (sudo -u postgres).")
            return DbAdminSession("local", db_host, db_port, "", "")
        print("[WARN] No fue posible usar sudo -u postgres en este servidor.")

    print("[INFO] Intentaremos conexión admin con usuario/contraseña en el servidor DB.")
    db_admin_user = ask_text("DB admin user", "postgres", required=True)
    db_admin_password = ask_secret("DB admin password")

    probe_cmd = (
        f"PGPASSWORD={_quote(db_admin_password)} psql -h {_quote(db_host)} -p {db_port} "
        f"-U {_quote(db_admin_user)} -d postgres -tAc \"SELECT 1;\""
    )
    probe = run(probe_cmd, check=False)
    if probe.returncode == 0 and "1" in probe.stdout:
        print("[OK] Conexión admin remota validada.")
        return DbAdminSession("remote", db_host, db_port, db_admin_user, db_admin_password)

    detail = probe.stderr.strip() or probe.stdout.strip() or "sin detalle"
    print(f"[ERROR] No se pudo conectar al servidor DB con credenciales admin: {detail}")
    print(
        "[INFO] Debes permitir la conexión al servidor PostgreSQL y usar un usuario con permisos completos (superuser/admin)."
    )
    return None


def _db_admin_psql_command(session: DbAdminSession, sql: str, psql_flags: str = "") -> str:
    flags = f"{psql_flags} " if psql_flags else ""
    if session.mode == "local":
        return f"sudo -u postgres psql -v ON_ERROR_STOP=1 -d postgres {flags}-c {shlex.quote(sql)}"

    return (
        f"PGPASSWORD={_quote(session.admin_password)} psql -v ON_ERROR_STOP=1 "
        f"-h {_quote(session.db_host)} -p {session.db_port} "
        f"-U {_quote(session.admin_user)} -d postgres {flags}-c {shlex.quote(sql)}"
    )


def _db_admin_dropdb_command(session: DbAdminSession, db_name: str) -> str:
    if session.mode == "local":
        return f"sudo -u postgres dropdb --if-exists {_quote(db_name)}"

    return (
        f"PGPASSWORD={_quote(session.admin_password)} dropdb --if-exists "
        f"-h {_quote(session.db_host)} -p {session.db_port} "
        f"-U {_quote(session.admin_user)} {_quote(db_name)}"
    )


def _list_instance_databases(
    instance: str,
    session: DbAdminSession,
) -> tuple[list[str], str | None]:
    instance_literal = _sql_literal(instance)
    sql = (
        "SELECT datname "
        "FROM pg_database "
        "WHERE datistemplate = false "
        f"AND datname LIKE '{instance_literal}%' "
        "ORDER BY datname;"
    )
    query_cmd = _db_admin_psql_command(session, sql, psql_flags="-tA")
    result = run(query_cmd, check=False)
    if result.returncode != 0:
        error_text = result.stderr.strip() or result.stdout.strip() or "Error desconocido"
        return [], error_text

    rows = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return rows, None


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
        print("[INFO] Operación cancelada.")
        return

    config = _validate_instance_or_abort(instance)
    if config is None:
        return

    filestore_dbs, filestore_root = _list_filestore_databases(config)

    session = _resolve_db_admin_access()
    db_names: list[str] = list(filestore_dbs)
    dbs_by_prefix: list[str] = []
    db_error: str | None = None
    if session:
        dbs_by_prefix, db_error = _list_instance_databases(instance, session)
        if db_error:
            print(f"[WARN] No se pudieron detectar DBs por prefijo '{instance}': {db_error}")
        for db_name in dbs_by_prefix:
            if db_name not in db_names:
                db_names.append(db_name)
    else:
        print(
            "[WARN] Se continuará con limpieza local (servicio/config/store). El borrado de DB/roles se omite por falta de conexión admin al servidor DB."
        )

    manual_dbs = ask_text(
        "DBs extra a eliminar (coma, opcional)",
        "",
        required=False,
    )
    if manual_dbs:
        for item in [name.strip() for name in manual_dbs.split(",") if name.strip()]:
            if item not in db_names:
                db_names.append(item)

    if db_names:
        print("\nDBs candidatas para eliminación:")
        for name in db_names:
            print(f"- {name}")
    else:
        print("[INFO] No hay DBs detectadas/indicadas para eliminar.")

    commands: list[Command] = [
        Command(
            "Detener servicio Odoo",
            f"systemctl stop {_quote(config.odoo_service)} || true",
        ),
        Command(
            "Deshabilitar servicio Odoo",
            f"systemctl disable {_quote(config.odoo_service)} || true",
        ),
        Command(
            "Eliminar unit file",
            f"rm -f {_quote(f'/etc/systemd/system/{config.odoo_service}.service')}",
        ),
        Command("Recargar systemd", "systemctl daemon-reload"),
        Command(
            "Eliminar configuración Odoo", f"rm -rf {_quote(config.odoo_conf_dir)}"
        ),
        Command("Eliminar home de instancia", f"rm -rf {_quote(config.odoo_home)}"),
        Command(
            "Eliminar usuario Linux de instancia",
            f"id -u {_quote(config.odoo_user)} >/dev/null 2>&1 && userdel -r {_quote(config.odoo_user)} || true",
        ),
        Command(
            "Eliminar logs Odoo/Nginx de instancia",
            f"rm -f {_quote(f'/var/log/odoo/{config.instance}.log')} {_quote(f'/var/log/nginx/{config.instance}.access.log')} {_quote(f'/var/log/nginx/{config.instance}.error.log')}",
        ),
        Command(
            "Eliminar Nginx HTTP",
            f"rm -f {_quote(f'/etc/nginx/sites-available/{config.nginx_http_name}')} {_quote(f'/etc/nginx/sites-enabled/{config.nginx_http_name}')}",
        ),
        Command(
            "Eliminar Nginx HTTPS",
            f"rm -f {_quote(f'/etc/nginx/sites-available/{config.nginx_https_name}')} {_quote(f'/etc/nginx/sites-enabled/{config.nginx_https_name}')}",
        ),
        Command("Eliminar SSL de instancia", f"rm -rf {_quote(config.nginx_ssl_dir)}"),
        Command("Eliminar raíz filestore de instancia", f"rm -rf {_quote(filestore_root)}"),
        Command("Validar/recargar Nginx (best effort)", "nginx -t && systemctl reload nginx || true"),
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
                    f"Cerrar conexiones activas de DB {db_name}",
                    _db_admin_psql_command(session, terminate_sql) + " || true",
                )
            )
            commands.append(
                Command(
                    f"Eliminar DB {db_name}",
                    _db_admin_dropdb_command(session, db_name),
                )
            )

        role_candidates = [config.instance, config.db_user]
        unique_roles: list[str] = []
        for role in role_candidates:
            if role and role not in unique_roles:
                unique_roles.append(role)

        for role in unique_roles:
            drop_role_sql = f"DROP ROLE IF EXISTS {role};"
            commands.append(
                Command(
                    f"Eliminar rol PostgreSQL {role} (si existe)",
                    _db_admin_psql_command(session, drop_role_sql) + " || true",
                )
            )

    print(f"\n{title('Resumen de eliminación total')}")
    summary_rows = [
        ["Instancia", instance],
        ["Servicio systemd detectado", "sí" if service_exists(config.odoo_service) else "no"],
        ["Home de instancia detectado", "sí" if path_exists(config.odoo_home) else "no"],
        ["Configuración detectada", "sí" if path_exists(config.odoo_conf_dir) else "no"],
        ["Nginx HTTP detectado", "sí" if path_exists(f"/etc/nginx/sites-available/{config.nginx_http_name}") else "no"],
        ["Nginx HTTPS detectado", "sí" if path_exists(f"/etc/nginx/sites-available/{config.nginx_https_name}") else "no"],
        ["SSL detectado", "sí" if path_exists(config.nginx_ssl_dir) else "no"],
        ["Filestore raíz detectado", f"{'sí' if path_exists(filestore_root) else 'no'} ({filestore_root})"],
        ["DBs por filestore", ", ".join(filestore_dbs) if filestore_dbs else "(ninguna)"],
        ["DBs por prefijo", ", ".join(dbs_by_prefix) if dbs_by_prefix else "(ninguna)"],
        ["Acceso admin DB", session.mode if session else "no disponible (solo limpieza local)"],
        ["DBs a eliminar", ", ".join(db_names) if db_names else "(ninguna detectada)"],
        ["Comandos a ejecutar", str(len(commands))],
    ]
    print(render_table(["Campo", "Valor"], summary_rows))

    if not confirm_with_phrase(
        "Acción SUPER destructiva detectada.",
        f"ELIMINAR-TODO {instance}",
    ):
        print("[INFO] Confirmación no válida. Operación cancelada.")
        return

    _execute_plan(commands)
