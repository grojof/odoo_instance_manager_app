"""Backup, restore, and duplicate instance data (database + filestore)."""

from __future__ import annotations

import datetime
import uuid

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
    if migration_mode == "Copiada (nuevo UUID en destino)":
        new_uuid = str(uuid.uuid4())
        sql_uuid = (
            "INSERT INTO ir_config_parameter (key, value, create_uid, create_date, write_uid, write_date) "
            f"VALUES ('database.uuid', '{new_uuid}', 1, NOW(), 1, NOW()) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, write_date = NOW();"
        )
        commands.append(
            Command(
                "Regenerar database.uuid en destino (modo Copiada)",
                f'PGPASSWORD={_quote(db_password)} psql -h {_quote(db_host)} -p {db_port} -U {_quote(db_user)} -d {_quote(target_db)} -c "{sql_uuid}"',
            )
        )

    if neutralize:
        commands.extend(
            [
                Command(
                    "Neutralizar cron en destino (si existe)",
                    f'PGPASSWORD={_quote(db_password)} psql -h {_quote(db_host)} -p {db_port} -U {_quote(db_user)} -d {_quote(target_db)} -c "UPDATE ir_cron SET active = false;" || true',
                ),
                Command(
                    "Neutralizar servidores de correo saliente (si existe)",
                    f'PGPASSWORD={_quote(db_password)} psql -h {_quote(db_host)} -p {db_port} -U {_quote(db_user)} -d {_quote(target_db)} -c "UPDATE ir_mail_server SET active = false;" || true',
                ),
                Command(
                    "Neutralizar fetchmail (si existe)",
                    f'PGPASSWORD={_quote(db_password)} psql -h {_quote(db_host)} -p {db_port} -U {_quote(db_user)} -d {_quote(target_db)} -c "UPDATE fetchmail_server SET active = false;" || true',
                ),
            ]
        )

    return commands


def _backup_instance(
    config: InstanceConfig, cached: DbCredentials | None = None
) -> DbCredentials | None:
    creds = _ask_db_credentials(config.instance, cached)
    db_name = _pick_db_name(creds, "DB origen para backup", required=True)
    if not db_name:
        print(level_text("INFO", "Sin DB origen, operación cancelada."))
        return creds
    if not _is_safe_path_component(db_name):
        print(level_text("ERROR", "Nombre de DB no válido para construir la ruta de filestore."))
        return creds

    db_host, db_port, db_user, db_password = creds.host, creds.port, creds.user, creds.password

    backup_dir = ask_text(
        "Directorio destino de backup", f"/var/backups/{config.instance}", required=True
    )
    backup_mode = choose(
        "Tipo de backup",
        ["Solo DB", "Solo Filestore", "DB + Filestore"],
        default_index=None,
    )
    if not backup_mode:
        print(level_text("INFO", "Operación cancelada."))
        return creds

    filestore_dir = _filestore_path(config, db_name)
    quoted_backup_dir = _quote(backup_dir)
    # One timestamp for the whole operation so the DB dump and the filestore
    # archive of the same backup share a suffix and can be paired.
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    dump_path = f"{backup_dir}/{config.instance}_{ts}.dump"
    archive_path = f"{backup_dir}/{config.instance}_{ts}.filestore.tar.gz"
    commands: list[Command] = [
        Command("Crear directorio de backup", f"mkdir -p {quoted_backup_dir}")
    ]

    if backup_mode in {"Solo DB", "DB + Filestore"}:
        commands.append(
            Command(
                "Exportar backup de DB (formato custom, atómico)",
                f"TMP={_quote(dump_path + '.partial')} && "
                f"PGPASSWORD={_quote(db_password)} pg_dump -h {_quote(db_host)} -p {db_port} -U {_quote(db_user)} -Fc -f \"$TMP\" {_quote(db_name)} && "
                f"mv \"$TMP\" {_quote(dump_path)} || {{ rm -f \"$TMP\"; exit 1; }}",
            )
        )

    if backup_mode in {"Solo Filestore", "DB + Filestore"}:
        commands.append(
            Command(
                "Exportar backup de Filestore (atómico)",
                f"TMP={_quote(archive_path + '.partial')} && "
                f"test -d {_quote(filestore_dir)} && "
                f"tar -czf \"$TMP\" -C {_quote(filestore_dir)} . && "
                f"mv \"$TMP\" {_quote(archive_path)} || {{ rm -f \"$TMP\"; exit 1; }}",
            )
        )

    _execute_plan(commands)
    print(level_text("INFO", f"Sufijo de backup: {ts}"))
    return creds


def _restore_backup(
    config: InstanceConfig, cached: DbCredentials | None = None
) -> DbCredentials | None:
    restore_mode = choose(
        "Tipo de restauración",
        ["Solo DB", "Solo Filestore", "DB + Filestore"],
        default_index=None,
    )
    if not restore_mode:
        print(level_text("INFO", "Operación cancelada."))
        return cached

    target_db = ask_text("DB destino", config.instance, required=True)
    if not _is_safe_path_component(target_db):
        print(level_text("ERROR", "Nombre de DB destino no válido para construir la ruta de filestore."))
        return cached
    migration_mode = choose(
        "Modo de operación (equivalente Odoo)",
        ["Copiada (nuevo UUID en destino)", "Movida (mantener UUID)"],
        default_index=None,
    )
    if not migration_mode:
        print(level_text("INFO", "Operación cancelada."))
        return cached
    neutralize = ask_bool("¿Neutralizar destino?", True)

    creds = _ask_db_credentials(config.instance, cached)
    db_host, db_port, db_user, db_password = creds.host, creds.port, creds.user, creds.password

    commands: list[Command] = []

    if restore_mode in {"Solo DB", "DB + Filestore"}:
        if database_exists(target_db):
            print(level_text("ERROR", f"La DB destino ya existe: {target_db}"))
            return creds

        print(level_text("INFO", "Selecciona archivo dump (.dump)"))
        dump_file = select_file_path(".", "Dump de base de datos", (".dump",))
        if not dump_file:
            print(level_text("INFO", "Operación cancelada."))
            return creds
        commands.extend(
            [
                Command(
                    "Crear DB destino",
                    f"PGPASSWORD={_quote(db_password)} createdb -h {_quote(db_host)} -p {db_port} -U {_quote(db_user)} -O {_quote(db_user)} {_quote(target_db)}",
                ),
                Command(
                    "Restaurar dump en DB destino",
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

    if restore_mode in {"Solo Filestore", "DB + Filestore"}:
        print(level_text("INFO", "Selecciona archivo backup de filestore (.tar.gz)"))
        filestore_backup = select_file_path(".", "Backup de filestore", (".tar.gz", ".tgz"))
        if not filestore_backup:
            print(level_text("INFO", "Operación cancelada."))
            return creds
        target_filestore = _filestore_path(config, target_db)
        overwrite_store = False
        if path_exists(target_filestore):
            overwrite_store = ask_bool(
                "El filestore destino existe, ¿sobrescribir?", False
            )
            if not overwrite_store:
                print(level_text("INFO", "Restauración de filestore cancelada por conflicto."))
                return creds

        commands.append(
            Command(
                "Crear ruta base de filestore", f"mkdir -p {_quote(target_filestore)}"
            )
        )
        if overwrite_store:
            commands.append(
                Command(
                    "Eliminar filestore previo", f"rm -rf {_quote(target_filestore)}/*"
                )
            )
        commands.append(
            Command(
                "Restaurar filestore en destino",
                f"tar -xzf {_quote(filestore_backup)} -C {_quote(target_filestore)}",
            )
        )

    if not confirm_with_phrase(
        "Acción sensible de restauración detectada.",
        f"RESTORE {config.instance}",
    ):
        print(level_text("INFO", "Confirmación no válida. Operación cancelada."))
        return creds

    _execute_plan(commands)
    return creds


def _duplicate_instance(
    config: InstanceConfig, cached: DbCredentials | None = None
) -> DbCredentials | None:
    creds = _ask_db_credentials(config.instance, cached)
    source_db = _pick_db_name(creds, "DB origen para duplicar", required=True)
    if not source_db:
        print(level_text("INFO", "Sin DB origen, operación cancelada."))
        return creds

    target_instance = ask_text("Nueva instancia destino", "", required=True)
    target_db = ask_text("Nueva DB destino", target_instance, required=True)

    target_config = InstanceConfig(instance=target_instance)
    target_config.db_user = target_db
    try:
        target_config.validate_identifiers()
    except ValueError as error:
        print(level_text("ERROR", str(error)))
        return creds
    if path_exists(target_config.odoo_home):
        print(level_text("ERROR", f"Ya existe {target_config.odoo_home}"))
        return creds
    if service_exists(target_instance):
        print(level_text("ERROR", f"Ya existe servicio systemd: {target_instance}"))
        return creds
    if database_exists(target_db):
        print(level_text("ERROR", f"Ya existe DB destino: {target_db}"))
        return creds

    db_host, db_port, db_user, db_password = creds.host, creds.port, creds.user, creds.password

    migration_mode = choose(
        "Modo de duplicación",
        ["Copiada (nuevo UUID en destino)", "Movida (mantener UUID)"],
        default_index=None,
    )
    if not migration_mode:
        print(level_text("INFO", "Operación cancelada."))
        return creds
    neutralize = ask_bool("¿Neutralizar DB duplicada?", True)
    duplicate_filestore = ask_bool("¿Duplicar también filestore?", True)

    commands: list[Command] = [
        Command(
            "Duplicar DB por plantilla",
            f"PGPASSWORD={_quote(db_password)} createdb -h {_quote(db_host)} -p {db_port} -U {_quote(db_user)} -T {_quote(source_db)} -O {_quote(db_user)} {_quote(target_db)}",
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
            print(level_text("ERROR", f"Ya existe filestore destino: {target_filestore}"))
            return creds

        target_parent = target_filestore.rsplit("/", 1)[0]
        commands.extend(
            [
                Command(
                    "Crear ruta base filestore destino",
                    f"mkdir -p {_quote(target_parent)}",
                ),
                Command(
                    "Duplicar filestore",
                    f"cp -a {_quote(source_filestore)} {_quote(target_filestore)}",
                ),
            ]
        )

    if not confirm_with_phrase(
        "Acción sensible de duplicación detectada.",
        f"DUPLICAR {config.instance}",
    ):
        print(level_text("INFO", "Confirmación no válida. Operación cancelada."))
        return creds

    _execute_plan(commands)
    return creds
