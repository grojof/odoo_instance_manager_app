"""UFW firewall management (server-wide)."""

from __future__ import annotations

from ..planners import plan_ufw_allow_port, plan_ufw_base_setup, plan_ufw_delete_rule
from ..prompts import ask_bool, ask_int, ask_text, choose
from ..system import Command, run
from ..ui import level_text, title
from .common import _execute_plan


def _show_ufw_status() -> None:
    print(f"\n{title('Estado UFW')}")
    result = run("ufw status verbose 2>&1", check=False)
    text = result.stdout.strip()
    if "command not found" in text or result.returncode != 0 and not text:
        print(level_text("INFO", "UFW no está instalado o no es accesible."))
        return
    print(text or "(sin salida)")


def _configure_base(config_hint_ip: str = "") -> None:
    print(f"\n{title('Configurar base segura de UFW')}")
    print(
        level_text(
            "WARN",
            "Asegúrate de que el puerto SSH es correcto antes de habilitar: una regla "
            "errónea puede dejarte fuera del servidor.",
        )
    )
    ssh_port = ask_int("Puerto SSH a permitir", 22)
    allow_http = ask_bool("¿Permitir HTTP (80)?", True)
    allow_https = ask_bool("¿Permitir HTTPS (443)?", True)
    pg_from_ip = ""
    if ask_bool("¿Permitir PostgreSQL (5432) desde una IP concreta (app server)?", False):
        pg_from_ip = ask_text("IP autorizada para PostgreSQL", config_hint_ip or "", required=True)

    commands = plan_ufw_base_setup(
        ssh_port=ssh_port,
        allow_http=allow_http,
        allow_https=allow_https,
        pg_from_ip=pg_from_ip,
    )
    _execute_plan(commands)


def _allow_port() -> None:
    port = ask_int("Puerto a permitir", 8069)
    proto = choose("Protocolo", ["tcp", "udp", "Volver"], default_index=0)
    if proto in {"", "Volver"}:
        return
    _execute_plan(plan_ufw_allow_port(port, proto))


def _delete_rule() -> None:
    result = run("ufw status numbered 2>&1", check=False)
    print(f"\n{title('Reglas UFW')}\n{result.stdout.strip() or '(sin reglas)'}")
    if result.returncode != 0:
        print(level_text("INFO", "No se pudieron listar las reglas (¿UFW instalado/activo?)."))
        return
    number = ask_int("Número de regla a eliminar", 1)
    _execute_plan(plan_ufw_delete_rule(number))


def _toggle(enable: bool) -> None:
    verb = "enable" if enable else "disable"
    _execute_plan([Command(f"UFW {verb}", f"ufw --force {verb}")])


def manage_firewall() -> None:
    while True:
        _show_ufw_status()
        action = choose(
            "Firewall (UFW)",
            [
                "Instalar/config base segura",
                "Permitir puerto",
                "Eliminar regla (por número)",
                "Habilitar UFW",
                "Deshabilitar UFW",
                "Volver",
            ],
            default_index=None,
        )
        if action in {"", "Volver"}:
            return
        if action == "Instalar/config base segura":
            _configure_base()
        elif action == "Permitir puerto":
            _allow_port()
        elif action == "Eliminar regla (por número)":
            _delete_rule()
        elif action == "Habilitar UFW":
            _toggle(True)
        elif action == "Deshabilitar UFW":
            _toggle(False)
