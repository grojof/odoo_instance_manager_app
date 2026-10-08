from __future__ import annotations

import os
import sys
from importlib import metadata

from instance_manager.i18n import set_language, t, tf
from instance_manager.prompts import choose, clear_screen
from instance_manager.ui import sanitize
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
    lang = choose('Idioma / Language', ["English", "Español"], default_index=0)
    set_language("es" if lang == "Español" else "en")


_USAGE = """usage: odoo-instance-manager [--help | --version]

Interactive installer and manager of Odoo instances on a Debian/Ubuntu host. Run it
as root, with no arguments: every action is a plan you preview and confirm.
OIM_LANG=es (or en) chooses the language without asking."""


def _version() -> str:
    try:
        return metadata.version("odoo-instance-manager")
    except metadata.PackageNotFoundError:
        return "unknown (not installed)"


def main(argv: list[str] | None = None) -> int:
    _configure_utf8_console()
    args = sys.argv[1:] if argv is None else argv
    if args and args[0] in {"-h", "--help"}:
        print(_USAGE)
        return 0
    if args and args[0] == "--version":
        print(f"odoo-instance-manager {_version()}")
        return 0
    if args:
        print(_USAGE, file=sys.stderr)
        return 2

    if os.geteuid() != 0:
        print(t('This manager requires administrative privileges.'))
        print(t('Run it as root: sudo odoo-instance-manager (or sudo python3 odoo_instance_manager.py from a checkout).'))
        return 1

    clear_screen()
    try:
        _select_language()
    except (KeyboardInterrupt, EOFError):
        print("\nExiting.")
        return 0
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
        except Exception as error:  # noqa: BLE001 - the last resort keeps the session
            # Anything else (an unreadable file, a host answering unexpectedly) is
            # reported by name and the menu stays, rather than a traceback.
            print(tf('\n[ERROR] Unexpected error ({}): {}. Returning to the menu.',
                     type(error).__name__, sanitize(str(error))))
            continue


if __name__ == "__main__":
    raise SystemExit(main())
