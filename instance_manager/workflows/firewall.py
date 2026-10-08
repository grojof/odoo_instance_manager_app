"""UFW firewall management (server-wide)."""

from __future__ import annotations

import re

from ..i18n import tf
from ..models import ip_error
from ..planners import plan_ufw_allow_port, plan_ufw_base_setup, plan_ufw_delete_rule
from ..prompts import ask_bool, ask_int, ask_text, choose
from ..system import Command, detect_ssh_ports, run
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
    detected = detect_ssh_ports()
    if detected:
        print(level_text("INFO", tf('SSH listens on: {}', ", ".join(str(port) for port in detected))))
    else:
        print(level_text("WARN", 'Could not detect the SSH port (sshd -T / ssh.socket).'))
    ssh_port = ask_int('SSH port to allow', detected[0] if detected else 22)
    if detected and ssh_port not in detected and not ask_bool(
        tf('SSH does not listen on {}: enabling UFW would lock new SSH sessions out. Continue anyway?', ssh_port),
        False,
    ):
        return
    allow_http = ask_bool('Allow HTTP (80)?', True)
    allow_https = ask_bool('Allow HTTPS (443)?', True)
    pg_from_ip = ""
    if ask_bool('Allow PostgreSQL (5432) from a specific IP (app server)?', False):
        # One address: `any` or a network would open PostgreSQL to more than the app server.
        pg_from_ip = ask_text('IP allowed for PostgreSQL', config_hint_ip or "", required=True, validate=ip_error)

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


def _numbered_rule_line(status: str, number: int) -> str | None:
    """The exact line of rule ``number`` in ``ufw status numbered`` output."""
    for line in status.splitlines():
        match = re.match(r"^\[\s*(\d+)\]", line)
        if match and int(match.group(1)) == number:
            return line
    return None


def _allows_ssh(line: str, ssh_ports: list[int]) -> bool:
    """Whether a ``ufw status numbered`` line allows one of SSH's ports."""
    if "ALLOW" not in line:
        return False
    if "OpenSSH" in line:
        return True
    return any(re.search(rf"(^|[\s\]]){port}(/tcp)?(\s|$)", line) for port in ssh_ports)


def _delete_rule() -> None:
    result = run("ufw status numbered 2>&1", check=False)
    print(f"\n{title('UFW rules')}\n{result.stdout.strip() or '(no rules)'}")
    if result.returncode != 0:
        print(level_text("INFO", 'Could not list the rules (is UFW installed/active?).'))
        return
    number = ask_int('Rule number to delete', 1, min_value=1, max_value=9999)
    expected = _numbered_rule_line(result.stdout, number)
    if expected is None:
        print(level_text("ERROR", tf('There is no rule #{}.', number)))
        return
    if _allows_ssh(expected, detect_ssh_ports() or [22]) and not ask_bool(
        'This rule lets SSH in: deleting it can lock you out of the server. Delete it anyway?', False
    ):
        return
    _execute_plan(plan_ufw_delete_rule(number, expected))


def _toggle(enable: bool) -> None:
    verb = "enable" if enable else "disable"
    commands = [Command(tf('UFW {}', verb), f"ufw --force {verb}")]
    if enable:
        # As the baseline does: SSH is allowed before the firewall goes up.
        ports = detect_ssh_ports()
        if not ports and not ask_bool(
            'Could not detect the SSH port: enabling UFW may lock you out. Enable anyway?', False
        ):
            return
        commands = [Command(tf('Allow SSH (port {})', port), f"ufw allow {int(port)}/tcp") for port in ports] + commands
    _execute_plan(commands)


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
