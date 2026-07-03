"""Scheduled automated backups for an instance via a systemd timer."""

from __future__ import annotations

from ..models import InstanceConfig
from ..planners import plan_remove_scheduled_backup, plan_scheduled_backup
from ..prompts import ask_bool, ask_int, ask_text, choose
from ..system import run
from ..ui import level_text, title
from .common import _execute_plan, _filestore_path, _is_safe_path_component

_ONCALENDAR = {
    "Diario (02:30)": "*-*-* 02:30:00",
    "Semanal (domingo 03:00)": "Sun *-*-* 03:00:00",
    "Mensual (día 1, 03:30)": "*-*-01 03:30:00",
}


def _configure_schedule(config: InstanceConfig) -> None:
    print(f"\n{title('Configurar backup programado')}")
    print(
        level_text(
            "INFO",
            "El backup se ejecuta como root usando 'sudo -u postgres pg_dump' (DB local, sin contraseña).",
        )
    )
    db_name = ask_text("Base de datos a respaldar", config.db_name or config.instance, required=True)
    if not _is_safe_path_component(db_name):
        print(level_text("ERROR", "Nombre de base de datos no válido."))
        return
    backup_dir = ask_text("Directorio destino", f"/var/backups/{config.instance}", required=True)
    include_filestore = ask_bool("¿Incluir también el filestore?", True)
    keep = ask_int("¿Cuántos backups conservar (retención)?", 7, min_value=1, max_value=365)
    schedule = choose("Frecuencia", [*list(_ONCALENDAR), "Volver"], default_index=0)
    if schedule in {"", "Volver"}:
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
    print(f"\n{title('Estado del backup programado')}")
    status = run(f"systemctl status {name}.timer --no-pager -n 5 2>&1", check=False)
    print(status.stdout.strip() or "(sin timer configurado)")
    nxt = run(f"systemctl list-timers {name}.timer --no-pager 2>&1", check=False)
    if nxt.stdout.strip():
        print("\n" + nxt.stdout.strip())


def _remove_schedule(config: InstanceConfig) -> None:
    _execute_plan(plan_remove_scheduled_backup(config))


def manage_scheduled_backup(config: InstanceConfig) -> None:
    while True:
        action = choose(
            f"Backups programados: {config.instance}",
            [
                "Configurar backup programado",
                "Ver estado",
                "Eliminar programación",
                "Volver",
            ],
            default_index=None,
        )
        if action in {"", "Volver"}:
            return
        if action == "Configurar backup programado":
            _configure_schedule(config)
        elif action == "Ver estado":
            _show_schedule_status(config)
        elif action == "Eliminar programación":
            _remove_schedule(config)
