"""Systemd service management for detected instance services."""

from __future__ import annotations

from ..i18n import tf
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
    print(f"\n{title('Detected instance services')}")
    if not services:
        print(level_text("INFO", 'No instance services detected in systemd.'))
        return

    rows: list[list[str]] = []
    for service_name in services:
        active_text = level_text("OK", 'running') if service_active(service_name) else level_text("MISSING", 'stopped')
        enabled_text = level_text("OK", 'autostart on') if service_enabled(service_name) else level_text("INFO", 'autostart off')
        rows.append([service_name, active_text, enabled_text])
    print(render_table(['Service', 'State', 'Startup'], rows))


def manage_instance_services() -> None:
    while True:
        services = _list_existing_instance_services()
        _show_services_table(services)

        action = choose(
            'Service actions',
            ['Select a service', 'Refresh', 'Back'],
            default_index=None,
        )
        if action in {"", 'Back'}:
            return
        if action == 'Refresh':
            continue

        service_name = ""
        if services:
            pick = choose(
                'Select a service',
                services + ['Type a name', 'Cancel'],
                default_index=None,
            )
            if pick in {"", 'Cancel'}:
                continue
            if pick == 'Type a name':
                service_name = ask_text('Service name', "", required=True)
            else:
                service_name = pick
        else:
            service_name = ask_text('Service name', "", required=True)

        service_action = choose(
            tf('Action for service {}', service_name),
            [
                'Start',
                'Stop',
                'Restart',
                'Enable autostart',
                'Disable autostart',
                'Cancel',
            ],
            default_index=None,
        )
        if service_action in {"", 'Cancel'}:
            continue

        if service_action == 'Start':
            commands = [Command(tf('Start service {}', service_name), f"systemctl start {_quote(service_name)}")]
        elif service_action == 'Stop':
            commands = [Command(tf('Stop service {}', service_name), f"systemctl stop {_quote(service_name)}")]
        elif service_action == 'Restart':
            commands = [Command(tf('Restart service {}', service_name), f"systemctl restart {_quote(service_name)}")]
        elif service_action == 'Enable autostart':
            commands = [Command(tf('Enable autostart {}', service_name), f"systemctl enable {_quote(service_name)}")]
        else:
            commands = [Command(tf('Disable autostart {}', service_name), f"systemctl disable {_quote(service_name)}")]

        _execute_plan(commands)
