"""Provisioning flows: install Odoo, PostgreSQL, or both, with port suggestion."""

from __future__ import annotations

import os
import re

from ..models import InstanceConfig
from ..planners import (
    plan_copy_custom_certs,
    plan_db_setup,
    plan_ensure_db_role,
    plan_ensure_self_signed_certs,
    plan_nginx_http,
    plan_nginx_https,
    plan_odoo_base_setup,
)
from ..prompts import ask_bool, ask_int, ask_text, choose, select_file_path
from ..system import (
    Command,
    apply_commands,
    list_instances,
    read_odoo_conf,
    run,
)
from ..ui import level_text
from .common import _execute_plan, _odoo_conf_candidates, _quote


def _collect_instance_config() -> InstanceConfig:
    while True:
        instance = ask_text("Nombre de instancia", "odoo18", required=True)
        config = InstanceConfig(instance=instance)
        config.version = ask_text("Versión Odoo", config.version, required=True)
        config.repo_branch = ask_text("Rama repo Odoo", config.repo_branch, required=True)
        config.domain = ask_text("Dominio público", config.domain, required=True)

        suggested_http, suggested_gevent = _suggest_instance_ports(
            base_http=config.http_port,
            base_gevent=config.gevent_port,
        )
        if (suggested_http, suggested_gevent) != (config.http_port, config.gevent_port):
            print(
                level_text(
                    "INFO",
                    f"Puertos sugeridos automáticamente por disponibilidad: HTTP={suggested_http}, gevent={suggested_gevent}",
                )
            )

        config.http_port = ask_int("Puerto HTTP interno Odoo", suggested_http)
        config.gevent_port = ask_int("Puerto gevent interno Odoo", suggested_gevent)
        config.db_host = ask_text("DB host", config.db_host, required=True)
        config.db_port = ask_int("DB port", config.db_port)
        config.db_user = ask_text("DB user", config.instance, required=True)
        config.db_password = ask_text("DB password", config.instance, required=True)
        config.db_name = ask_text(
            "DB nombre (opcional para validaciones)", "", required=False
        )
        config.app_server_ip = ask_text(
            "IP servidor app para regla pg_hba", config.app_server_ip, required=True
        )
        config.odoo_admin_passwd = ask_text(
            "admin_passwd Odoo", config.instance, required=True
        )
        config.normalize_defaults()

        try:
            config.validate_identifiers()
            return config
        except ValueError as error:
            print(level_text("ERROR", str(error)))
            print(
                level_text(
                    "INFO",
                    "Vuelve a introducir los datos de instalación con un formato seguro.",
                )
            )


def _build_partial_install_cleanup(
    config: InstanceConfig, cleanup_db_role: bool
) -> list[Command]:
    commands: list[Command] = [
        Command(
            "[Cleanup] Detener servicio Odoo",
            f"systemctl stop {_quote(config.odoo_service)} || true",
        ),
        Command(
            "[Cleanup] Deshabilitar servicio Odoo",
            f"systemctl disable {_quote(config.odoo_service)} || true",
        ),
        Command(
            "[Cleanup] Eliminar unit file",
            f"rm -f {_quote(f'/etc/systemd/system/{config.odoo_service}.service')}",
        ),
        Command("[Cleanup] Recargar systemd", "systemctl daemon-reload"),
        Command(
            "[Cleanup] Eliminar configuración Odoo",
            f"rm -rf {_quote(config.odoo_conf_dir)}",
        ),
        Command(
            "[Cleanup] Eliminar home de instancia", f"rm -rf {_quote(config.odoo_home)}"
        ),
        Command(
            "[Cleanup] Eliminar Nginx HTTP",
            f"rm -f {_quote(f'/etc/nginx/sites-available/{config.nginx_http_name}')} {_quote(f'/etc/nginx/sites-enabled/{config.nginx_http_name}')}",
        ),
        Command(
            "[Cleanup] Eliminar Nginx HTTPS",
            f"rm -f {_quote(f'/etc/nginx/sites-available/{config.nginx_https_name}')} {_quote(f'/etc/nginx/sites-enabled/{config.nginx_https_name}')}",
        ),
        Command(
            "[Cleanup] Eliminar SSL de instancia",
            f"rm -rf {_quote(config.nginx_ssl_dir)}",
        ),
        Command("[Cleanup] Recargar Nginx", "systemctl reload nginx || true"),
    ]

    if cleanup_db_role:
        commands.append(
            Command(
                "[Cleanup] Eliminar rol PostgreSQL de la instancia (si existe)",
                f'sudo -u postgres psql -v ON_ERROR_STOP=1 -c "DROP ROLE IF EXISTS {config.db_user};" || true',
            )
        )

    return commands


def _execute_install_with_cleanup(
    commands: list[Command],
    config: InstanceConfig,
    cleanup_db_role: bool,
) -> None:
    try:
        _execute_plan(commands)
    except (RuntimeError, KeyboardInterrupt) as error:
        reason = (
            "interrumpida (Ctrl+C)"
            if isinstance(error, KeyboardInterrupt)
            else "falló"
        )
        cleanup_commands = _build_partial_install_cleanup(
            config, cleanup_db_role=cleanup_db_role
        )
        print(
            f"\n{level_text('WARN', f'La instalación {reason}. Ejecutando limpieza automática de residuos de la instancia...')}"
        )
        apply_commands(cleanup_commands, stop_on_error=False)
        print(
            level_text(
                "WARN",
                "Limpieza automática finalizada. Revisa los mensajes anteriores.",
            )
        )
        # Return to the menu instead of crashing the CLI with an uncaught raise.
        return


def _choose_nginx_mode() -> str:
    return choose(
        "Modo Nginx para la instancia",
        ["No tocar Nginx", "Configurar HTTP", "Configurar HTTPS"],
        default_index=None,
    )


def _maybe_plan_certs(config: InstanceConfig) -> list[Command]:
    cert_mode = choose(
        "Gestión de certificados para HTTPS",
        [
            "No tocar certificados",
            "Autofirmado (detectar o generar automáticamente)",
            "Let's Encrypt (gestionado externamente)",
            "Copiar certificados propios (CRT/KEY[/Intermediate])",
        ],
        default_index=None,
    )

    if cert_mode in {"", "No tocar certificados", "Let's Encrypt (gestionado externamente)"}:
        return []

    if cert_mode == "Autofirmado (detectar o generar automáticamente)":
        return plan_ensure_self_signed_certs(config)

    print(level_text("INFO", "Selecciona el certificado público (server.crt)"))
    cert_src = select_file_path(
        ".",
        "Certificado público (CRT)",
        (".crt", ".pem", ".cer"),
    )
    print(level_text("INFO", "Selecciona la clave privada (server.key)"))
    key_src = select_file_path(
        ".",
        "Clave privada (KEY)",
        (".key", ".pem"),
    )
    use_intermediate = ask_bool("¿Tienes archivo intermedio?", True)
    intermediate_src = None
    if use_intermediate:
        print(level_text("INFO", "Selecciona la cadena intermedia/cabundle"))
        intermediate_src = select_file_path(
            ".",
            "Cadena intermedia (CA bundle / intermediate)",
            (".crt", ".pem", ".cer", ".bundle", ".ca-bundle"),
        )

    return plan_copy_custom_certs(config, cert_src, key_src, intermediate_src)


def _extract_port_from_token(token: str) -> int | None:
    cleaned = token.strip().strip("[]")
    if ":" not in cleaned:
        return None
    maybe_port = cleaned.rsplit(":", 1)[-1]
    if not maybe_port.isdigit():
        return None
    port = int(maybe_port)
    if 1 <= port <= 65535:
        return port
    return None


def _ports_from_active_listeners() -> set[int]:
    ports: set[int] = set()
    result = run("ss -ltnH", check=False)
    if result.returncode != 0:
        return ports

    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        local_address = parts[3]
        port = _extract_port_from_token(local_address)
        if port is not None:
            ports.add(port)
    return ports


def _ports_from_odoo_configs() -> set[int]:
    ports: set[int] = set()
    for instance in list_instances(InstanceConfig.base_instances_dir):
        values: dict[str, str] = {}
        for conf_path in _odoo_conf_candidates(instance):
            values = read_odoo_conf(conf_path)
            if values:
                break
        for key in ("http_port", "gevent_port", "longpolling_port"):
            value = values.get(key, "").strip()
            if value.isdigit():
                port = int(value)
                if 1 <= port <= 65535:
                    ports.add(port)
    return ports


def _ports_from_nginx_configs() -> set[int]:
    ports: set[int] = set()
    nginx_dirs = ["/etc/nginx/sites-available", "/etc/nginx/sites-enabled"]
    patterns = [
        re.compile(r"\blisten\s+(\d{1,5})\b"),
        re.compile(r"\bserver\s+[0-9.]+:(\d{1,5})\b"),
        re.compile(r"\bproxy_pass\s+https?://[0-9.]+:(\d{1,5})\b"),
    ]

    for folder in nginx_dirs:
        if not os.path.isdir(folder):
            continue
        for name in sorted(os.listdir(folder)):
            file_path = os.path.join(folder, name)
            if os.path.islink(file_path):
                target = os.path.realpath(file_path)
                if os.path.isfile(target):
                    file_path = target
            if not os.path.isfile(file_path):
                continue

            try:
                with open(file_path, encoding="utf-8", errors="replace") as file_handle:
                    for raw_line in file_handle:
                        line = raw_line.strip()
                        if not line or line.startswith("#"):
                            continue
                        for pattern in patterns:
                            for match in pattern.findall(line):
                                if match.isdigit():
                                    port = int(match)
                                    if 1 <= port <= 65535:
                                        ports.add(port)
            except OSError:
                continue

    return ports


def _collect_reserved_ports() -> set[int]:
    ports = set()
    ports.update(_ports_from_active_listeners())
    ports.update(_ports_from_odoo_configs())
    ports.update(_ports_from_nginx_configs())
    return ports


def _suggest_instance_ports(base_http: int, base_gevent: int) -> tuple[int, int]:
    reserved = _collect_reserved_ports()
    offset = base_gevent - base_http
    if offset <= 0:
        offset = 3

    start = max(1024, base_http)
    max_http = 65535 - offset
    for http_port in range(start, max_http + 1):
        gevent_port = http_port + offset
        if http_port in reserved or gevent_port in reserved:
            continue
        return http_port, gevent_port

    return base_http, base_gevent


def install_odoo_only() -> None:
    config = _collect_instance_config()
    service_autostart = ask_bool(
        "¿Habilitar autoarranque del servicio Odoo al iniciar el servidor?",
        True,
    )
    commands: list[Command] = []
    commands.extend(plan_ensure_db_role(config))
    commands.extend(plan_odoo_base_setup(config, service_autostart=service_autostart))

    nginx_mode = _choose_nginx_mode()
    if nginx_mode == "Configurar HTTP":
        commands.extend(plan_nginx_http(config))
    elif nginx_mode == "Configurar HTTPS":
        commands.extend(_maybe_plan_certs(config))
        commands.extend(plan_nginx_https(config))

    _execute_install_with_cleanup(commands, config, cleanup_db_role=False)


def install_db_only() -> None:
    config = _collect_instance_config()
    ensure_remote_access = ask_bool(
        "¿Configurar listen_addresses y pg_hba para acceso remoto?", True
    )
    commands = plan_db_setup(config, ensure_remote_access=ensure_remote_access)
    _execute_install_with_cleanup(commands, config, cleanup_db_role=True)


def install_odoo_and_db() -> None:
    config = _collect_instance_config()
    service_autostart = ask_bool(
        "¿Habilitar autoarranque del servicio Odoo al iniciar el servidor?",
        True,
    )
    commands: list[Command] = []
    commands.extend(plan_db_setup(config, ensure_remote_access=True))
    commands.extend(plan_odoo_base_setup(config, service_autostart=service_autostart))

    nginx_mode = _choose_nginx_mode()
    if nginx_mode == "Configurar HTTP":
        commands.extend(plan_nginx_http(config))
    elif nginx_mode == "Configurar HTTPS":
        commands.extend(_maybe_plan_certs(config))
        commands.extend(plan_nginx_https(config))

    _execute_install_with_cleanup(commands, config, cleanup_db_role=True)
