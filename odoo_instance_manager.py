from __future__ import annotations

import os
import sys

from instance_manager.prompts import choose, clear_screen
from instance_manager.workflows import (
    external_server_report,
    install_db_only,
    install_odoo_and_db,
    install_odoo_only,
    manage_existing_instance,
    manage_fail2ban,
    manage_firewall,
    manage_instance_services,
    purge_instance_superuser,
)


def _configure_utf8_console() -> None:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def _installation_menu() -> None:
    while True:
        action = choose(
            "\nMenú de instalación",
            [
                "Instalar instancia Odoo",
                "Instalar PostgreSQL (sin Odoo)",
                "Instalar instancia Odoo + PostgreSQL",
                "Volver",
            ],
            default_index=None,
        )

        if action in {"", "Volver"}:
            return
        if action == "Instalar instancia Odoo":
            install_odoo_only()
        elif action == "Instalar PostgreSQL (sin Odoo)":
            install_db_only()
        elif action == "Instalar instancia Odoo + PostgreSQL":
            install_odoo_and_db()


def main() -> int:
    _configure_utf8_console()

    if os.geteuid() != 0:
        print("Este gestor requiere permisos de administración.")
        print("Ejecuta con: sudo python3 odoo_instance_manager.py")
        return 1

    clear_screen()
    print("Odoo Instance Manager")
    print("- Instalación interactiva por instancia")
    print("- Soporta instancia Odoo + usuario de PostgreSQL, PosgreSQL o ambos")
    print("- Muestra el listado de comandos a ejecutar para cada acción")

    while True:
        try:
            action = choose(
                "\n¿Qué quieres hacer?",
                [
                    "Servicios instancias",
                    "Gestionar instancias",
                    "Seguridad Fail2ban",
                    "Firewall (UFW)",
                    "Menú de instalación",
                    "Eliminar instancias (Incluye configs, servicios, logs, etc.)",
                    "Informe para servidor externo",
                    "Salir",
                ],
                default_index=None,
            )
        except (KeyboardInterrupt, EOFError):
            print("\nSaliendo.")
            return 0

        if not action:
            continue

        try:
            if action == "Servicios instancias":
                manage_instance_services()
            elif action == "Gestionar instancias":
                manage_existing_instance()
            elif action == "Seguridad Fail2ban":
                manage_fail2ban()
            elif action == "Firewall (UFW)":
                manage_firewall()
            elif action == "Menú de instalación":
                _installation_menu()
            elif action == "Eliminar instancias (Incluye configs, servicios, logs, etc.)":
                purge_instance_superuser()
            elif action == "Informe para servidor externo":
                external_server_report()
            elif action == "Salir":
                return 0
            else:
                continue
        except KeyboardInterrupt:
            print("\nOperación interrumpida. Volviendo al menú.")
            continue
        except EOFError:
            print("\nEntrada cerrada. Saliendo.")
            return 0
        except RuntimeError as error:
            # A command in a plan failed (already reported by apply_commands):
            # surface it and return to the menu instead of crashing the CLI.
            print(f"\n[ERROR] La operación no se completó: {error}")
            continue


if __name__ == "__main__":
    raise SystemExit(main())
