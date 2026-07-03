"""Systemd service management for detected instance services."""

from __future__ import annotations

from ..models import InstanceConfig
from ..prompts import ask_text, choose
from ..system import (
    Command,
    list_instances,
    service_active,
    service_enabled,
    service_exists,
)
from ..ui import level_text, render_table, title
from .common import _execute_plan, _quote


def _list_existing_instance_services() -> list[str]:
    services: list[str] = []
    for instance in list_instances(InstanceConfig.base_instances_dir):
        if service_exists(instance):
            services.append(instance)
    return sorted(set(services))


def _show_services_table(services: list[str]) -> None:
    print(f"\n{title('Servicios de instancias detectados')}")
    if not services:
        print(level_text("INFO", "No se detectaron servicios de instancia en systemd."))
        return

    rows: list[list[str]] = []
    for service_name in services:
        active_text = level_text("OK", "en marcha") if service_active(service_name) else level_text("MISSING", "detenido")
        enabled_text = level_text("OK", "autoarranque sí") if service_enabled(service_name) else level_text("INFO", "autoarranque no")
        rows.append([service_name, active_text, enabled_text])
    print(render_table(["Servicio", "Estado", "Arranque"], rows))


def manage_instance_services() -> None:
    while True:
        services = _list_existing_instance_services()
        _show_services_table(services)

        action = choose(
            "Acciones de servicios",
            ["Seleccionar servicio", "Refrescar", "Volver"],
            default_index=None,
        )
        if action in {"", "Volver"}:
            return
        if action == "Refrescar":
            continue

        service_name = ""
        if services:
            pick = choose(
                "Selecciona servicio",
                services + ["Escribir nombre", "Cancelar"],
                default_index=None,
            )
            if pick in {"", "Cancelar"}:
                continue
            if pick == "Escribir nombre":
                service_name = ask_text("Nombre de servicio", "", required=True)
            else:
                service_name = pick
        else:
            service_name = ask_text("Nombre de servicio", "", required=True)

        service_action = choose(
            f"Acción para servicio {service_name}",
            [
                "Iniciar",
                "Detener",
                "Reiniciar",
                "Habilitar autoarranque",
                "Deshabilitar autoarranque",
                "Cancelar",
            ],
            default_index=None,
        )
        if service_action in {"", "Cancelar"}:
            continue

        if service_action == "Iniciar":
            commands = [Command(f"Iniciar servicio {service_name}", f"systemctl start {_quote(service_name)}")]
        elif service_action == "Detener":
            commands = [Command(f"Detener servicio {service_name}", f"systemctl stop {_quote(service_name)}")]
        elif service_action == "Reiniciar":
            commands = [Command(f"Reiniciar servicio {service_name}", f"systemctl restart {_quote(service_name)}")]
        elif service_action == "Habilitar autoarranque":
            commands = [Command(f"Habilitar autoarranque {service_name}", f"systemctl enable {_quote(service_name)}")]
        else:
            commands = [Command(f"Deshabilitar autoarranque {service_name}", f"systemctl disable {_quote(service_name)}")]

        _execute_plan(commands)
