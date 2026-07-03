"""Disk usage report and backup retention cleanup for an instance."""

from __future__ import annotations

from ..models import InstanceConfig
from ..planners import plan_backup_retention
from ..prompts import ask_int, ask_text, choose
from ..system import path_exists, run
from ..ui import level_text, render_table, title
from .common import _execute_plan, _quote, _resolve_data_dir


def _size_of(path: str) -> str:
    if not path_exists(path):
        return "(no existe)"
    result = run(f"du -sh {_quote(path)} 2>/dev/null | cut -f1", check=False)
    return result.stdout.strip() or "?"


def _log_size(config: InstanceConfig) -> str:
    result = run(
        f"du -ch {_quote(config.odoo_log_file)}* 2>/dev/null | tail -1 | cut -f1",
        check=False,
    )
    return result.stdout.strip() or "(sin logs)"


def _disk_usage_report(config: InstanceConfig, backup_dir: str) -> None:
    data_dir = _resolve_data_dir(config)
    print(f"\n{title(f'Uso de disco: {config.instance}')}")
    rows = [
        ["Home instancia", config.odoo_home, _size_of(config.odoo_home)],
        ["Data dir (filestore)", data_dir, _size_of(data_dir)],
        ["Logs de Odoo", f"{config.odoo_log_file}*", _log_size(config)],
        ["Directorio de backups", backup_dir, _size_of(backup_dir)],
    ]
    print(render_table(["Elemento", "Ruta", "Tamaño"], rows))

    print(f"\n{title('Espacio libre del sistema de ficheros (data dir)')}")
    df = run(f"df -Ph {_quote(data_dir)} 2>/dev/null", check=False)
    print(df.stdout.strip() or "(no medible)")

    if path_exists(backup_dir):
        print(f"\n{title('Backups presentes (más recientes primero)')}")
        listing = run(
            f"ls -lht {_quote(backup_dir)} 2>/dev/null | grep -E '\\.dump$|\\.tar\\.gz$' | head -20",
            check=False,
        )
        print(listing.stdout.strip() or "(sin backups)")


def _cleanup_old_backups(config: InstanceConfig, backup_dir: str) -> None:
    if not path_exists(backup_dir):
        print(level_text("INFO", f"No existe el directorio de backups: {backup_dir}"))
        return
    keep = ask_int(
        "¿Cuántos backups recientes conservar (por tipo)?", 5, min_value=1, max_value=365
    )
    commands = plan_backup_retention(config, backup_dir, keep)
    _execute_plan(commands)


def manage_disk_usage(config: InstanceConfig) -> None:
    backup_dir = ask_text(
        "Directorio de backups a revisar", f"/var/backups/{config.instance}", required=True
    )
    while True:
        action = choose(
            f"Uso de disco y limpieza: {config.instance}",
            [
                "Ver uso de disco",
                "Limpiar backups antiguos (retención)",
                "Volver",
            ],
            default_index=None,
        )
        if action in {"", "Volver"}:
            return
        if action == "Ver uso de disco":
            _disk_usage_report(config, backup_dir)
        elif action == "Limpiar backups antiguos (retención)":
            _cleanup_old_backups(config, backup_dir)
