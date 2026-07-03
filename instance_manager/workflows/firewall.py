"""UFW firewall management (server-wide)."""

from __future__ import annotations

from ..i18n import tf
from ..planners import plan_ufw_allow_port, plan_ufw_base_setup, plan_ufw_delete_rule
from ..prompts import ask_bool, ask_int, ask_text, choose
from ..system import Command, run
from ..ui import level_text, title
from .common import _execute_plan


def _show_ufw_status() -> None:
    print(f"\n{title('UFW status')}")
    result = run("ufw status verbose 2>&1", check=False)
    text = result.stdout.strip()
    if "command not found" in text or result.returncode != 0 and not text:
        print(level_text("INFO", 'UFW is not installed or not accessible.'))
        return
    print(text or '(no output)')


def _configure_base(config_hint_ip: str = "") -> None:
    print(f"\n{title('Configure a secure UFW baseline')}")
    print(
        level_text(
            "WARN",
            'Make sure the SSH port is correct before enabling: a wrong rule can lock you out of the server.',
        )
    )
    ssh_port = ask_int('SSH port to allow', 22)
    allow_http = ask_bool('Allow HTTP (80)?', True)
    allow_https = ask_bool('Allow HTTPS (443)?', True)
    pg_from_ip = ""
    if ask_bool('Allow PostgreSQL (5432) from a specific IP (app server)?', False):
        pg_from_ip = ask_text('IP allowed for PostgreSQL', config_hint_ip or "", required=True)

    commands = plan_ufw_base_setup(
        ssh_port=ssh_port,
        allow_http=allow_http,
        allow_https=allow_https,
        pg_from_ip=pg_from_ip,
    )
    _execute_plan(commands)


def _allow_port() -> None:
    port = ask_int('Port to allow', 8069)
    proto = choose('Protocol', ["tcp", "udp", 'Back'], default_index=0)
    if proto in {"", 'Back'}:
        return
    _execute_plan(plan_ufw_allow_port(port, proto))


def _delete_rule() -> None:
    result = run("ufw status numbered 2>&1", check=False)
    print(f"\n{title('UFW rules')}\n{result.stdout.strip() or '(no rules)'}")
    if result.returncode != 0:
        print(level_text("INFO", 'Could not list the rules (is UFW installed/active?).'))
        return
    number = ask_int('Rule number to delete', 1)
    _execute_plan(plan_ufw_delete_rule(number))


def _toggle(enable: bool) -> None:
    verb = "enable" if enable else "disable"
    _execute_plan([Command(tf('UFW {}', verb), f"ufw --force {verb}")])


def manage_firewall() -> None:
    while True:
        _show_ufw_status()
        action = choose(
            'Firewall (UFW)',
            [
                'Install / configure secure baseline',
                'Allow a port',
                'Delete a rule (by number)',
                'Enable UFW',
                'Disable UFW',
                'Back',
            ],
            default_index=None,
        )
        if action in {"", 'Back'}:
            return
        if action == 'Install / configure secure baseline':
            _configure_base()
        elif action == 'Allow a port':
            _allow_port()
        elif action == 'Delete a rule (by number)':
            _delete_rule()
        elif action == 'Enable UFW':
            _toggle(True)
        elif action == 'Disable UFW':
            _toggle(False)
