"""Fail2ban base setup, per-instance jails, and ban operations."""

from __future__ import annotations

import ipaddress
import re

from ..planners import (
    plan_fail2ban_base_setup,
    plan_fail2ban_enable_odoo_instance,
    plan_fail2ban_ensure_odoo_filter,
)
from ..prompts import ask_bool, ask_int, ask_text, choose
from ..system import (
    Command,
    path_exists,
    run,
)
from ..ui import level_text, render_table, title
from .common import _execute_plan, _quote, _select_existing_instance


def _fail2ban_jail_name_for_instance(instance: str) -> str:
    token = re.sub(r"[^a-zA-Z0-9_-]+", "_", (instance or "").strip())
    return f"odoo-auth-{token}"


def _list_fail2ban_jails() -> list[str]:
    result = run("fail2ban-client status", check=False)
    if result.returncode != 0:
        return []

    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if "Jail list:" not in line:
            continue
        _, jail_text = line.split("Jail list:", 1)
        jails = [item.strip() for item in jail_text.split(",") if item.strip()]
        return sorted(set(jails))
    return []


def _list_banned_ips_for_jail(jail_name: str) -> tuple[list[str], str | None]:
    result = run(f"fail2ban-client status {_quote(jail_name)}", check=False)
    if result.returncode != 0:
        error_text = result.stderr.strip() or result.stdout.strip() or "No se pudo consultar el jail."
        return [], error_text

    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if "Banned IP list:" not in line:
            continue
        _, banned_text = line.split("Banned IP list:", 1)
        ips = [item.strip() for item in banned_text.split() if item.strip()]
        return sorted(set(ips)), None

    return [], None


def _extract_ipv4_candidates_from_line(line: str) -> list[str]:
    candidates: list[str] = []

    nginx_match = re.match(r"^\s*(\d{1,3}(?:\.\d{1,3}){3})\s+-\s+-\s+\[", line)
    if nginx_match:
        candidates.append(nginx_match.group(1))

    odoo_from_match = re.search(r"\bfrom\s+(\d{1,3}(?:\.\d{1,3}){3})\b", line)
    if odoo_from_match:
        candidates.append(odoo_from_match.group(1))

    return candidates


def _valid_ipv4(value: str) -> str | None:
    try:
        parsed = ipaddress.ip_address(value)
    except ValueError:
        return None
    if parsed.version != 4:
        return None
    return str(parsed)


def _assess_fail2ban_log_ip_quality(log_path: str) -> tuple[str, str]:
    if not path_exists(log_path):
        return "unknown", f"No existe el log: {log_path}"

    sample = run(f"tail -n 300 {_quote(log_path)}", check=False)
    if sample.returncode != 0:
        return "unknown", "No se pudo leer el log para evaluar IPs."

    private_ips: set[str] = set()
    public_ips: set[str] = set()

    for line in sample.stdout.splitlines():
        for candidate in _extract_ipv4_candidates_from_line(line):
            ip_value = _valid_ipv4(candidate)
            if not ip_value:
                continue
            ip_obj = ipaddress.ip_address(ip_value)
            if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local:
                private_ips.add(ip_value)
            else:
                public_ips.add(ip_value)

    if not private_ips and not public_ips:
        return "unknown", "No se detectaron IPs válidas en las últimas líneas del log."

    if public_ips:
        sample_public = ", ".join(sorted(public_ips)[:3])
        return "public-ok", f"IPs públicas detectadas en log (ej.: {sample_public})."

    sample_private = ", ".join(sorted(private_ips)[:3])
    return (
        "private-only",
        f"Solo se detectaron IPs internas/privadas en log (ej.: {sample_private}). Riesgo de banear gateway/proxy.",
    )


def _show_fail2ban_status() -> None:
    print(f"\n{title('Estado Fail2ban')}")
    service_state = run("systemctl is-active fail2ban", check=False)
    enabled_state = run("systemctl is-enabled fail2ban", check=False)
    ping_ready = run(
        "for i in $(seq 1 5); do fail2ban-client ping >/dev/null 2>&1 && exit 0; sleep 1; done; exit 1",
        check=False,
    )
    client_status = run("fail2ban-client status", check=False)

    client_value = "OK" if client_status.returncode == 0 else "ERROR"
    if (
        client_status.returncode != 0
        and service_state.returncode == 0
        and service_state.stdout.strip() == "active"
        and ping_ready.returncode != 0
    ):
        client_value = "WAIT"

    rows: list[list[str]] = [
        ["Servicio activo", service_state.stdout.strip() if service_state.returncode == 0 else "inactivo/no instalado"],
        ["Autoarranque", enabled_state.stdout.strip() if enabled_state.returncode == 0 else "desconocido"],
        ["Cliente fail2ban", client_value],
    ]
    print(render_table(["Chequeo", "Valor"], rows))

    if client_status.returncode == 0 and client_status.stdout.strip():
        print("\n" + client_status.stdout.strip())
    elif client_value == "WAIT":
        print(
            level_text(
                "WARN",
                "fail2ban está activo pero el socket aún no responde. Espera unos segundos y refresca estado.",
            )
        )
    elif client_status.stderr.strip():
        print(level_text("WARN", client_status.stderr.strip()))


def manage_fail2ban() -> None:
    while True:
        _show_fail2ban_status()

        action = choose(
            "Gestión de Fail2ban",
            [
                "Instalar/config base segura",
                "Activar protección Odoo por instancia",
                "Verificar IP real en log Odoo",
                "Ver estado y jails",
                "Ver detalle de jail",
                "Desbanear IP de jail",
                "Probar regex Odoo",
                "Volver",
            ],
            default_index=None,
        )

        if action in {"", "Volver"}:
            return

        if action == "Instalar/config base segura":
            extra_ignore = ask_text(
                "IPs/redes admin a excluir (separa por espacio/coma)",
                "",
                required=False,
            )
            extra_tokens = [
                token.strip()
                for token in extra_ignore.replace(",", " ").split()
                if token.strip()
            ]
            ignore_ips = " ".join(["127.0.0.1/8", "::1", *extra_tokens])
            bantime = ask_text("bantime", "1h", required=True)
            findtime = ask_text("findtime", "10m", required=True)
            maxretry = ask_int("maxretry", 8, min_value=1, max_value=1000)
            recidive_bantime = ask_text("recidive bantime", "24h", required=True)

            commands = plan_fail2ban_base_setup(
                ignore_ips=ignore_ips,
                bantime=bantime,
                findtime=findtime,
                maxretry=maxretry,
                recidive_bantime=recidive_bantime,
            )
            _execute_plan(commands)
            continue

        if action == "Activar protección Odoo por instancia":
            instance = _select_existing_instance()
            if not instance:
                print(level_text("INFO", "Operación cancelada."))
                continue

            default_log_path = f"/var/log/odoo/{instance}.log"
            log_path = ask_text("Ruta log Odoo de la instancia", default_log_path, required=True)
            ip_quality, ip_message = _assess_fail2ban_log_ip_quality(log_path)
            if ip_quality == "private-only":
                print(level_text("WARN", ip_message))
                if not ask_bool(
                    "¿Continuar igualmente con jail Odoo? (no recomendado)",
                    False,
                ):
                    print(level_text("INFO", "Activación cancelada para evitar baneo de gateway/proxy."))
                    continue
            elif ip_quality == "public-ok":
                print(level_text("OK", ip_message))
            else:
                print(level_text("WARN", ip_message))

            bantime = ask_text("bantime instancia", "1h", required=True)
            findtime = ask_text("findtime instancia", "10m", required=True)
            maxretry = ask_int("maxretry instancia", 8, min_value=1, max_value=1000)

            commands = plan_fail2ban_enable_odoo_instance(
                instance=instance,
                log_path=log_path,
                bantime=bantime,
                findtime=findtime,
                maxretry=maxretry,
            )
            _execute_plan(commands)
            continue

        if action == "Verificar IP real en log Odoo":
            instance = ask_text("Instancia (para sugerir log)", "", required=False)
            default_log_path = f"/var/log/odoo/{instance}.log" if instance else "/var/log/odoo/odoo.log"
            log_path = ask_text("Ruta log Odoo", default_log_path, required=True)
            ip_quality, ip_message = _assess_fail2ban_log_ip_quality(log_path)
            if ip_quality == "public-ok":
                print(level_text("OK", ip_message))
            elif ip_quality == "private-only":
                print(level_text("WARN", ip_message))
                print(level_text("INFO", "Recomendación: NO activar jail Odoo hasta recibir IP cliente real."))
            else:
                print(level_text("WARN", ip_message))
            continue

        if action == "Ver estado y jails":
            _show_fail2ban_status()
            continue

        if action == "Ver detalle de jail":
            jails = _list_fail2ban_jails()
            if jails:
                jail_name = choose(
                    "Selecciona jail",
                    jails + ["Escribir jail", "Cancelar"],
                    default_index=None,
                )
                if jail_name in {"", "Cancelar"}:
                    continue
                if jail_name == "Escribir jail":
                    jail_name = ask_text("Nombre jail", "", required=True)
            else:
                jail_name = ask_text("Nombre jail", "", required=True)

            result = run(f"fail2ban-client status {_quote(jail_name)}", check=False)
            if result.returncode == 0:
                print("\n" + (result.stdout.strip() or "(sin salida)"))
            else:
                print(level_text("ERROR", result.stderr.strip() or result.stdout.strip() or "No se pudo obtener estado del jail."))
            continue

        if action == "Desbanear IP de jail":
            instance_hint = ask_text("Instancia (opcional, para sugerir jail)", "", required=False)
            default_jail = _fail2ban_jail_name_for_instance(instance_hint) if instance_hint else ""
            jails = _list_fail2ban_jails()
            if jails:
                suggested_index = None
                if default_jail and default_jail in jails:
                    suggested_index = jails.index(default_jail)
                jail_pick = choose(
                    "Selecciona jail para desbanear",
                    jails + ["Escribir jail", "Cancelar"],
                    default_index=suggested_index,
                )
                if jail_pick in {"", "Cancelar"}:
                    continue
                if jail_pick == "Escribir jail":
                    jail_name = ask_text("Jail fail2ban", default_jail, required=True)
                else:
                    jail_name = jail_pick
            else:
                jail_name = ask_text("Jail fail2ban", default_jail, required=True)

            banned_ips, banned_error = _list_banned_ips_for_jail(jail_name)
            if banned_error:
                print(level_text("WARN", banned_error))

            ip_value = ""
            if banned_ips:
                print(f"\n{title('IPs actualmente baneadas en el jail')}" )
                print(render_table(["#", "IP"], [[str(index), ip] for index, ip in enumerate(banned_ips, start=1)]))
                ip_pick = choose(
                    "Selecciona IP a desbanear",
                    banned_ips + ["Escribir IP manual", "Cancelar"],
                    default_index=None,
                )
                if ip_pick in {"", "Cancelar"}:
                    continue
                if ip_pick == "Escribir IP manual":
                    ip_value = ask_text("IP a desbanear", "", required=True)
                else:
                    ip_value = ip_pick
            else:
                print(level_text("INFO", "No hay IPs baneadas detectadas en ese jail o no se pudo listarlas."))
                ip_value = ask_text("IP a desbanear", "", required=True)

            commands = [
                Command(
                    f"Desbanear {ip_value} en {jail_name}",
                    f"fail2ban-client set {_quote(jail_name)} unbanip {_quote(ip_value)}",
                )
            ]
            _execute_plan(commands)
            continue

        if action == "Probar regex Odoo":
            instance = ask_text("Instancia (para sugerir log)", "", required=False)
            default_log_path = f"/var/log/odoo/{instance}.log" if instance else "/var/log/odoo/odoo.log"
            log_path = ask_text("Ruta log Odoo", default_log_path, required=True)
            filter_path = ask_text(
                "Ruta filtro fail2ban",
                "/etc/fail2ban/filter.d/odoo-auth.conf",
                required=True,
            )
            commands: list[Command] = [
                Command("Validar archivo log", f"test -f {_quote(log_path)}"),
            ]
            if filter_path == "/etc/fail2ban/filter.d/odoo-auth.conf":
                commands.extend(plan_fail2ban_ensure_odoo_filter())
            commands.extend(
                [
                    Command("Validar archivo filtro", f"test -f {_quote(filter_path)}"),
                    Command(
                        "Probar regex fail2ban",
                        f"fail2ban-regex {_quote(log_path)} {_quote(filter_path)}",
                    ),
                ]
            )
            _execute_plan(commands)
