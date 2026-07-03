from __future__ import annotations

import os
import sys

from instance_manager.i18n import set_language, t, tf
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
            '\nInstallation menu',
            [
                'Install Odoo instance',
                'Install PostgreSQL (without Odoo)',
                'Install Odoo instance + PostgreSQL',
                'Back',
            ],
            default_index=None,
        )

        if action in {"", 'Back'}:
            return
        if action == 'Install Odoo instance':
            install_odoo_only()
        elif action == 'Install PostgreSQL (without Odoo)':
            install_db_only()
        elif action == 'Install Odoo instance + PostgreSQL':
            install_odoo_and_db()


def _select_language() -> None:
    env = os.environ.get("OIM_LANG", "").strip().lower()
    if env in {"en", "es"}:
        set_language(env)
        return
    lang = choose('Idioma / Language', ["Español", "English"], default_index=0)
    set_language("en" if lang == "English" else "es")


def main() -> int:
    _configure_utf8_console()

    if os.geteuid() != 0:
        print(t('This manager requires administrative privileges.'))
        print(t('Run with: sudo python3 odoo_instance_manager.py'))
        return 1

    clear_screen()
    _select_language()
    print(t("Odoo Instance Manager"))
    print(t('- Interactive per-instance installation'))
    print(t('- Supports an Odoo instance + PostgreSQL user, PostgreSQL, or both'))
    print(t('- Shows the list of commands to run for each action'))

    while True:
        try:
            action = choose(
                '\nWhat do you want to do?',
                [
                    'Instance services',
                    'Manage instances',
                    'Fail2ban security',
                    'Firewall (UFW)',
                    'Installation menu',
                    'Remove instances (configs, services, logs, …)',
                    'External server report',
                    'Exit',
                ],
                default_index=None,
            )
        except (KeyboardInterrupt, EOFError):
            print(t('\nExiting.'))
            return 0

        if not action:
            continue

        try:
            if action == 'Instance services':
                manage_instance_services()
            elif action == 'Manage instances':
                manage_existing_instance()
            elif action == 'Fail2ban security':
                manage_fail2ban()
            elif action == 'Firewall (UFW)':
                manage_firewall()
            elif action == 'Installation menu':
                _installation_menu()
            elif action == 'Remove instances (configs, services, logs, …)':
                purge_instance_superuser()
            elif action == 'External server report':
                external_server_report()
            elif action == 'Exit':
                return 0
            else:
                continue
        except KeyboardInterrupt:
            print(t('\nOperation interrupted. Returning to the menu.'))
            continue
        except EOFError:
            print(t('\nInput closed. Exiting.'))
            return 0
        except RuntimeError as error:
            # A command in a plan failed (already reported by apply_commands):
            # surface it and return to the menu instead of crashing the CLI.
            print(tf('\n[ERROR] The operation did not complete: {}', error))
            continue


if __name__ == "__main__":
    raise SystemExit(main())
