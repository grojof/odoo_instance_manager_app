from __future__ import annotations

import datetime
import ipaddress
import os
import re
import shlex
import socket
import uuid

from .models import InstanceConfig
from .planners import (
    _is_local_db_host,
    _sql_literal,
    plan_copy_custom_certs,
    plan_db_setup,
    plan_ensure_db_role,
    plan_ensure_self_signed_certs,
    plan_fail2ban_base_setup,
    plan_fail2ban_enable_odoo_instance,
    plan_fail2ban_ensure_odoo_filter,
    plan_nginx_http,
    plan_nginx_https,
    plan_odoo_base_setup,
    pretty_paths,
)
from .prompts import (
    ask_bool,
    ask_int,
    ask_text,
    choose,
    confirm_with_phrase,
    select_file_path,
)
from .system import (
    Command,
    apply_commands,
    database_exists,
    db_role_exists,
    list_databases,
    list_instances,
    path_exists,
    preview_commands,
    read_odoo_conf,
    require_root_for_apply,
    run,
    service_active,
    service_enabled,
    service_exists,
    user_exists,
)
from .ui import level_tag, level_text, render_table, strip_ansi, title


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


def _execute_plan(commands: list[Command]) -> None:
    if not commands:
        print(level_text("INFO", "No hay acciones para ejecutar."))
        return

    preview_commands(commands)
    mode = choose(
        "Confirmar acción",
        ["Cancelar", "Confirmar plan y ejecutar"],
        default_index=None,
    )
    if mode in {"", "Cancelar"}:
        return
    require_root_for_apply()
    apply_commands(commands)
    print(f"\n{level_text('OK', 'Plan ejecutado correctamente.')}")


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


def _quote(value: str) -> str:
    return shlex.quote(value)


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


def _default_odoo_conf_path(instance: str) -> str:
    return f"/etc/odoo/{instance}/{instance}.conf"


def _legacy_odoo_conf_path(instance: str) -> str:
    return f"/etc/{instance}/odoo.conf"


def _odoo_conf_candidates(instance: str) -> list[str]:
    return [_default_odoo_conf_path(instance), _legacy_odoo_conf_path(instance)]


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


def _collect_db_connection(instance: str) -> tuple[str, int, str, str] | None:
    wants_db_query = ask_bool(
        "¿Quieres conectarte a PostgreSQL para listar DBs disponibles?",
        False,
    )
    if not wants_db_query:
        return None

    db_host = ask_text("DB server", "127.0.0.1", required=True)
    db_port = ask_int("DB port", 5432)
    db_user = ask_text("DB user", instance, required=True)
    db_password = ask_text("DB password", None, required=True)
    return db_host, db_port, db_user, db_password


def _select_db_name(instance: str, label: str, required: bool = True) -> str:
    db_name = ""
    db_connection = _collect_db_connection(instance)
    if db_connection:
        db_host, db_port, db_user, db_password = db_connection
        db_names, error = list_databases(db_host, db_port, db_user, db_password)
        if error:
            print(f"[WARN] No se pudo listar DBs: {error}")
        elif db_names:
            print("\nDBs disponibles:")
            for item in db_names:
                print(f"- {item}")
            pick = choose(
                f"{label} (selección rápida)",
                db_names + ["Escribir nombre manualmente"],
                default_index=None,
            )
            if pick and pick != "Escribir nombre manualmente":
                db_name = pick
        else:
            print("[INFO] La conexión fue exitosa, pero no hay DBs listadas.")

    if db_name:
        return db_name

    return ask_text(label, "", required=required)


def _list_detected_instances(base_dir: str) -> list[str]:
    instances = list_instances(base_dir)
    print(f"\nInstancias detectadas en {base_dir}:")
    if not instances:
        print("  No se detectaron carpetas de instancia en el directorio base.")
        print("  Puedes escribir el nombre de una instancia conocida")
        print("  para eliminar otros datos residuales como configs, servicios, logs, etc.")
    for item in instances:
        print(f"- {item}")
    return instances


def _select_existing_instance() -> str:
    base_dir = InstanceConfig.base_instances_dir
    instances = _list_detected_instances(base_dir)

    if instances:
        selected = choose(
            "Selecciona instancia detectada",
            instances + ["Escribir nombre", "Cancelar"],
            default_index=None,
        )
        if selected == "Cancelar" or selected == "":
            return ""
        if selected != "Escribir nombre":
            return selected

    return ask_text("Nombre de instancia", "", required=False)


def _validate_instance_or_abort(instance: str) -> InstanceConfig | None:
    """Build and validate a config for a destructive flow.

    Returns a normalized, validated ``InstanceConfig`` or ``None`` when the
    instance identifier is unsafe (printing a descriptive error). Callers must
    treat ``None`` as "abort back to the menu" and never build a plan from an
    unvalidated name.
    """
    config = InstanceConfig(instance=instance)
    config.normalize_defaults()
    try:
        config.validate_identifiers()
    except ValueError as error:
        print(level_text("ERROR", str(error)))
        return None
    return config


def _is_safe_path_component(name: str) -> bool:
    """True if ``name`` is safe to embed as a single filesystem path component.

    Guards against path traversal when an operator-entered database name is
    interpolated into a filestore path that is created, archived, or deleted.
    """
    return (
        bool(name)
        and "/" not in name
        and "\\" not in name
        and "\x00" not in name
        and name not in {".", ".."}
        and not name.startswith(".")
    )


def _probe_databases_for_management(instance: str) -> tuple[str, str | None, list[str]]:
    db_name = ""
    db_error: str | None = None
    listed_dbs: list[str] = []

    db_connection = _collect_db_connection(instance)
    if db_connection:
        db_host, db_port, db_user, db_password = db_connection
        listed_dbs, db_error = list_databases(db_host, db_port, db_user, db_password)
        if db_error:
            print(f"[WARN] Fallo al consultar DBs: {db_error}")
        elif listed_dbs:
            print("\nDBs disponibles:")
            for item in listed_dbs:
                print(f"- {item}")
            selected = choose(
                "Selecciona DB para validaciones (opcional)",
                listed_dbs + ["No seleccionar"],
                default_index=None,
            )
            if selected and selected != "No seleccionar":
                db_name = selected
        else:
            print("[INFO] Conexión a DB exitosa, sin bases listadas.")

    if not db_name:
        db_name = ask_text("DB para validaciones (opcional)", "", required=False)

    return db_name, db_error, listed_dbs


def _resolve_data_dir(config: InstanceConfig) -> str:
    values = read_odoo_conf(config.odoo_conf_file)
    data_dir = values.get("data_dir", "").strip()
    if data_dir:
        return data_dir
    return f"{config.odoo_home}/.local/share/Odoo"


def _filestore_path(config: InstanceConfig, db_name: str) -> str:
    data_dir = _resolve_data_dir(config)
    return f"{data_dir}/filestore/{db_name}"


def _read_nginx_https_ssl_paths(config: InstanceConfig) -> tuple[str, str]:
    nginx_https_conf = f"/etc/nginx/sites-available/{config.nginx_https_name}"
    if not path_exists(nginx_https_conf):
        return "", ""

    cert_path = ""
    key_path = ""
    try:
        with open(nginx_https_conf, encoding="utf-8") as file_handle:
            for raw_line in file_handle:
                line = raw_line.strip().rstrip(";")
                if line.startswith("ssl_certificate_key "):
                    key_path = line.split(maxsplit=1)[1].strip()
                elif line.startswith("ssl_certificate "):
                    cert_path = line.split(maxsplit=1)[1].strip()
    except OSError:
        return "", ""

    return cert_path, key_path


def _is_self_signed_certificate(cert_path: str) -> bool:
    if not cert_path or not path_exists(cert_path):
        return False

    result = run(
        f"openssl x509 -in {_quote(cert_path)} -noout -subject -issuer",
        check=False,
    )
    if result.returncode != 0:
        return False

    subject_line = ""
    issuer_line = ""
    for line in result.stdout.splitlines():
        normalized = line.strip()
        if normalized.startswith("subject="):
            subject_line = normalized[len("subject=") :].strip()
        elif normalized.startswith("issuer="):
            issuer_line = normalized[len("issuer=") :].strip()

    return bool(subject_line and issuer_line and subject_line == issuer_line)


def _detect_certificate_mode(config: InstanceConfig) -> tuple[str, bool]:
    cert_path, key_path = _read_nginx_https_ssl_paths(config)
    if not cert_path and not key_path:
        return "No configurado", False

    if "/etc/letsencrypt/" in cert_path or "/etc/letsencrypt/" in key_path:
        return "Let's Encrypt", path_exists(cert_path) and path_exists(key_path)

    if cert_path == config.ssl_fullchain_file and key_path == config.ssl_key_file:
        has_expected_files = path_exists(config.ssl_fullchain_file) and path_exists(
            config.ssl_key_file
        )
        if _is_self_signed_certificate(config.ssl_cert_file):
            return "Autofirmado", has_expected_files
        return "Personalizado (CA)", has_expected_files

    if cert_path and key_path:
        return "Personalizado (externo)", path_exists(cert_path) and path_exists(key_path)

    return "Configuración TLS incompleta", False


def _post_db_mode_commands(
    db_host: str,
    db_port: int,
    db_user: str,
    db_password: str,
    target_db: str,
    migration_mode: str,
    neutralize: bool,
) -> list[Command]:
    commands: list[Command] = []
    if migration_mode == "Copiada (nuevo UUID en destino)":
        new_uuid = str(uuid.uuid4())
        sql_uuid = (
            "INSERT INTO ir_config_parameter (key, value, create_uid, create_date, write_uid, write_date) "
            f"VALUES ('database.uuid', '{new_uuid}', 1, NOW(), 1, NOW()) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, write_date = NOW();"
        )
        commands.append(
            Command(
                "Regenerar database.uuid en destino (modo Copiada)",
                f'PGPASSWORD={_quote(db_password)} psql -h {_quote(db_host)} -p {db_port} -U {_quote(db_user)} -d {_quote(target_db)} -c "{sql_uuid}"',
            )
        )

    if neutralize:
        commands.extend(
            [
                Command(
                    "Neutralizar cron en destino (si existe)",
                    f'PGPASSWORD={_quote(db_password)} psql -h {_quote(db_host)} -p {db_port} -U {_quote(db_user)} -d {_quote(target_db)} -c "UPDATE ir_cron SET active = false;" || true',
                ),
                Command(
                    "Neutralizar servidores de correo saliente (si existe)",
                    f'PGPASSWORD={_quote(db_password)} psql -h {_quote(db_host)} -p {db_port} -U {_quote(db_user)} -d {_quote(target_db)} -c "UPDATE ir_mail_server SET active = false;" || true',
                ),
                Command(
                    "Neutralizar fetchmail (si existe)",
                    f'PGPASSWORD={_quote(db_password)} psql -h {_quote(db_host)} -p {db_port} -U {_quote(db_user)} -d {_quote(target_db)} -c "UPDATE fetchmail_server SET active = false;" || true',
                ),
            ]
        )

    return commands


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


def _show_instance_status(
    config: InstanceConfig,
    db_error: str | None = None,
    listed_dbs: list[str] | None = None,
) -> None:
    print(f"\n{title('Ubicaciones y nombres esperados')}")
    path_rows = [[key, value] for key, value in pretty_paths(config)]
    print(render_table(["Campo", "Valor"], path_rows))

    conf_values = read_odoo_conf(config.odoo_conf_file)
    data_dir = _resolve_data_dir(config)

    print(f"\n{title('Estado detectado')}")
    status_rows: list[list[str]] = [
        ["OK" if user_exists(config.odoo_user) else "MISSING", "Linux user", config.odoo_user],
        ["OK" if path_exists(config.odoo_home) else "MISSING", "Odoo home", config.odoo_home],
        ["OK" if path_exists(config.odoo_conf_file) else "MISSING", "Odoo conf", config.odoo_conf_file],
        ["OK" if service_exists(config.odoo_service) else "MISSING", "systemd service", config.odoo_service],
        ["OK" if service_active(config.odoo_service) else "MISSING", "service active", config.odoo_service],
        ["OK" if db_role_exists(config.db_user) else "MISSING", "DB role", config.db_user],
        ["OK" if path_exists(data_dir) else "MISSING", "Data dir", data_dir],
    ]
    cert_mode, cert_ok = _detect_certificate_mode(config)
    status_rows.append(["OK" if cert_ok else "MISSING", "Certificado TLS", cert_mode])

    if db_error:
        status_rows.append(["MISSING", "DB listing", f"fallo de conexión/consulta -> {db_error}"])
    elif listed_dbs is not None:
        status_rows.append(["OK", "DB listing", f"{len(listed_dbs)} DB(s) detectada(s)"])

    if config.db_name:
        status_rows.append([
            "OK" if database_exists(config.db_name) else "MISSING",
            "DB database",
            config.db_name,
        ])
    else:
        status_rows.append(["INFO", "DB database", "no indicada, se omite validación"])

    labeled_rows = [[level_tag(state), label, value] for state, label, value in status_rows]
    print(render_table(["Estado", "Chequeo", "Valor"], labeled_rows))

    if conf_values:
        print(f"\n{title('Valores útiles en config Odoo')}")
        conf_rows: list[list[str]] = []
        for key in [
            "db_host",
            "db_port",
            "db_user",
            "addons_path",
            "data_dir",
            "http_port",
            "gevent_port",
        ]:
            if key in conf_values:
                conf_rows.append([key, conf_values[key]])
        if conf_rows:
            print(render_table(["Clave", "Valor"], conf_rows))


def _show_instance_locations(config: InstanceConfig) -> None:
    print(f"\n{title('Ubicaciones relevantes de la instancia')}")
    rows = [
        ["Odoo config", config.odoo_conf_file],
        ["Odoo home", config.odoo_home],
        ["Nginx HTTP", f"/etc/nginx/sites-available/{config.nginx_http_name}"],
        ["Nginx HTTPS", f"/etc/nginx/sites-available/{config.nginx_https_name}"],
        ["SSL dir", config.nginx_ssl_dir],
        ["Data store (data_dir)", _resolve_data_dir(config)],
    ]
    print(render_table(["Elemento", "Ruta/Valor"], rows))


def _repair_instance_nginx_logs(config: InstanceConfig) -> None:
    access_log = f"/var/log/nginx/{config.instance}.access.log"
    error_log = f"/var/log/nginx/{config.instance}.error.log"

    commands: list[Command] = [
        Command(
            "Asegurar directorio /var/log/nginx",
            "install -d -m 755 -o root -g adm /var/log/nginx",
        ),
        Command(
            "Recrear access log de instancia",
            f"install -m 640 -o www-data -g adm /dev/null {_quote(access_log)}",
        ),
        Command(
            "Recrear error log de instancia",
            f"install -m 640 -o www-data -g adm /dev/null {_quote(error_log)}",
        ),
        Command("Validar Nginx", "nginx -t"),
        Command(
            "Reabrir logs Nginx",
            "nginx -s reopen || systemctl reload nginx",
        ),
        Command(
            "Mostrar permisos finales de logs",
            f"ls -l {_quote(access_log)} {_quote(error_log)}",
        ),
    ]

    _execute_plan(commands)


def _install_python_packages_in_instance_venv(config: InstanceConfig) -> None:
    venv_activate = f"{config.odoo_home}/venv/bin/activate"
    venv_pip = f"{config.odoo_home}/venv/bin/pip"

    print(f"\n{title('Instalar paquetes Python en venv de la instancia')}")
    print(level_text("INFO", f"Venv objetivo: {config.odoo_home}/venv"))

    mode = choose(
        "Origen de paquetes",
        [
            "requirements.txt (seleccionar ruta)",
            "Lista manual de paquetes",
            "Cancelar",
        ],
        default_index=None,
    )
    if mode in {"", "Cancelar"}:
        return

    commands: list[Command] = [
        Command(
            "Validar venv de la instancia",
            f"test -x {_quote(venv_pip)}",
        )
    ]

    if mode == "requirements.txt (seleccionar ruta)":
        print(level_text("INFO", "Selecciona el archivo requirements a instalar."))
        req_path = select_file_path(
            ".",
            "Archivo requirements (TXT/IN)",
            (".txt", ".in"),
        )
        commands.append(
            Command(
                "Validar archivo requirements",
                f"test -f {_quote(req_path)}",
            )
        )
        commands.append(
            Command(
                "Instalar paquetes desde requirements en venv",
                f"sudo -u {_quote(config.odoo_user)} bash -lc \"source {_quote(venv_activate)} && pip install -r {_quote(req_path)}\"",
            )
        )
    else:
        print(level_text("INFO", "Formato manual soportado:"))
        print(level_text("INFO", "- Separados por comas en una línea"))
        print(level_text("INFO", "- O una dependencia por línea (Enter en vacío para terminar)"))
        print(level_text("INFO", "- requests"))
        print(level_text("INFO", "- psycopg2-binary==2.9.10"))
        print(level_text("INFO", "- babel>=2.14,<3"))

        raw_packages = ask_text(
            "Lista inicial de paquetes (coma o línea única)",
            "",
            required=False,
        )

        extra_lines: list[str] = []
        print(level_text("INFO", "Añade más paquetes (una línea por paquete). Enter vacío para finalizar."))
        while True:
            line = input("Paquete adicional: ").strip()
            if not line:
                break
            extra_lines.append(line)

        chunks: list[str] = []
        if raw_packages:
            chunks.append(raw_packages)
        chunks.extend(extra_lines)

        packages: list[str] = []
        for chunk in chunks:
            parts = [item.strip() for item in chunk.split(",") if item.strip()]
            packages.extend(parts)

        if not packages:
            print(level_text("WARN", "No se detectaron paquetes válidos. Operación cancelada."))
            return

        package_args = " ".join(_quote(package) for package in packages)
        commands.append(
            Command(
                "Instalar paquetes en venv",
                f"sudo -u {_quote(config.odoo_user)} bash -lc \"source {_quote(venv_activate)} && pip install {package_args}\"",
            )
        )

    commands.append(
        Command(
            "Mostrar paquetes instalados (resumen)",
            f"sudo -u {_quote(config.odoo_user)} bash -lc \"source {_quote(venv_activate)} && pip list\"",
        )
    )

    _execute_plan(commands)


def update_existing_configs(instance: str) -> None:
    config = InstanceConfig(instance=instance)
    config.normalize_defaults()

    print("\nIntroduce nuevos valores (si aplican)")
    config.domain = ask_text("Dominio", config.domain, required=True)
    config.http_port = ask_int("HTTP interno", config.http_port)
    config.gevent_port = ask_int("gevent interno", config.gevent_port)
    config.db_host = ask_text("DB host", config.db_host, required=True)
    config.db_port = ask_int("DB port", config.db_port)
    config.db_user = ask_text("DB user", config.db_user, required=True)
    config.db_password = ask_text("DB password", config.db_password, required=True)
    config.odoo_admin_passwd = ask_text(
        "admin_passwd Odoo", config.odoo_admin_passwd, required=True
    )

    backup_root = f"/var/backups/{config.instance}/config_preupdate"
    # One timestamped directory for the whole pre-update backup, so all files
    # land together instead of scattering across per-command timestamps.
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dest = f"{backup_root}/{ts}"
    backup_sources = [
        ("config odoo", config.odoo_conf_file),
        ("systemd service", f"/etc/systemd/system/{config.odoo_service}.service"),
        ("nginx http", f"/etc/nginx/sites-available/{config.nginx_http_name}"),
        ("nginx https", f"/etc/nginx/sites-available/{config.nginx_https_name}"),
    ]
    backup_rows = [[name, source, f"{backup_dest}/{name.replace(' ', '_')}"] for name, source in backup_sources]
    print(f"\n{title('Backup de configuración previo a actualización')}")
    print(render_table(["Elemento", "Origen", "Destino backup"], backup_rows))

    backup_commands: list[Command] = [
        Command(
            "Crear directorio de backup de configuración",
            f"mkdir -p {_quote(backup_dest)}",
        )
    ]
    for name, source in backup_sources:
        target_name = name.replace(" ", "_")
        backup_commands.append(
            Command(
                f"Backup previo de {name}",
                f"test -f {_quote(source)} && cp -a {_quote(source)} {_quote(f'{backup_dest}/{target_name}')} || true",
            )
        )

    commands: list[Command] = []
    commands.extend(backup_commands)
    commands.extend(
        plan_odoo_base_setup(
            config,
            service_autostart=service_enabled(config.odoo_service),
        )
    )

    nginx_mode = choose(
        "Regenerar Nginx",
        ["No", "Sí - HTTP", "Sí - HTTPS"],
        default_index=None,
    )
    if nginx_mode == "Sí - HTTP":
        commands.extend(plan_nginx_http(config))
    elif nginx_mode == "Sí - HTTPS":
        commands.extend(_maybe_plan_certs(config))
        commands.extend(plan_nginx_https(config))

    _execute_plan(commands)
    print(level_text("INFO", f"Backup de configuración (si se ejecutó el plan) en: {backup_dest}"))


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
            maxretry = ask_int("maxretry", 8)
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
            maxretry = ask_int("maxretry instancia", 8)

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


def _backup_instance(config: InstanceConfig) -> None:
    db_name = _select_db_name(config.instance, "DB origen para backup", required=True)
    if not db_name:
        print("[INFO] Sin DB origen, operación cancelada.")
        return
    if not _is_safe_path_component(db_name):
        print(level_text("ERROR", "Nombre de DB no válido para construir la ruta de filestore."))
        return

    db_host = ask_text("DB server", "127.0.0.1", required=True)
    db_port = ask_int("DB port", 5432)
    db_user = ask_text("DB user", config.instance, required=True)
    db_password = ask_text("DB password", None, required=True)

    backup_dir = ask_text(
        "Directorio destino de backup", f"/var/backups/{config.instance}", required=True
    )
    backup_mode = choose(
        "Tipo de backup",
        ["Solo DB", "Solo Filestore", "DB + Filestore"],
        default_index=None,
    )
    if not backup_mode:
        print("[INFO] Operación cancelada.")
        return

    filestore_dir = _filestore_path(config, db_name)
    quoted_backup_dir = _quote(backup_dir)
    # One timestamp for the whole operation so the DB dump and the filestore
    # archive of the same backup share a suffix and can be paired.
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    dump_path = f"{backup_dir}/{config.instance}_{ts}.dump"
    archive_path = f"{backup_dir}/{config.instance}_{ts}.filestore.tar.gz"
    commands: list[Command] = [
        Command("Crear directorio de backup", f"mkdir -p {quoted_backup_dir}")
    ]

    if backup_mode in {"Solo DB", "DB + Filestore"}:
        commands.append(
            Command(
                "Exportar backup de DB (formato custom, atómico)",
                f"TMP={_quote(dump_path + '.partial')} && "
                f"PGPASSWORD={_quote(db_password)} pg_dump -h {_quote(db_host)} -p {db_port} -U {_quote(db_user)} -Fc -f \"$TMP\" {_quote(db_name)} && "
                f"mv \"$TMP\" {_quote(dump_path)} || {{ rm -f \"$TMP\"; exit 1; }}",
            )
        )

    if backup_mode in {"Solo Filestore", "DB + Filestore"}:
        commands.append(
            Command(
                "Exportar backup de Filestore (atómico)",
                f"TMP={_quote(archive_path + '.partial')} && "
                f"test -d {_quote(filestore_dir)} && "
                f"tar -czf \"$TMP\" -C {_quote(filestore_dir)} . && "
                f"mv \"$TMP\" {_quote(archive_path)} || {{ rm -f \"$TMP\"; exit 1; }}",
            )
        )

    _execute_plan(commands)
    print(level_text("INFO", f"Sufijo de backup: {ts}"))


def _restore_backup(config: InstanceConfig) -> None:
    restore_mode = choose(
        "Tipo de restauración",
        ["Solo DB", "Solo Filestore", "DB + Filestore"],
        default_index=None,
    )
    if not restore_mode:
        print("[INFO] Operación cancelada.")
        return

    target_db = ask_text("DB destino", config.instance, required=True)
    if not _is_safe_path_component(target_db):
        print(level_text("ERROR", "Nombre de DB destino no válido para construir la ruta de filestore."))
        return
    migration_mode = choose(
        "Modo de operación (equivalente Odoo)",
        ["Copiada (nuevo UUID en destino)", "Movida (mantener UUID)"],
        default_index=None,
    )
    if not migration_mode:
        print("[INFO] Operación cancelada.")
        return
    neutralize = ask_bool("¿Neutralizar destino?", True)

    db_host = ask_text("DB server", "127.0.0.1", required=True)
    db_port = ask_int("DB port", 5432)
    db_user = ask_text("DB user", config.instance, required=True)
    db_password = ask_text("DB password", None, required=True)

    commands: list[Command] = []

    if restore_mode in {"Solo DB", "DB + Filestore"}:
        if database_exists(target_db):
            print(f"[ERROR] La DB destino ya existe: {target_db}")
            return

        print("Selecciona archivo dump (.dump)")
        dump_file = select_file_path(".")
        commands.extend(
            [
                Command(
                    "Crear DB destino",
                    f"PGPASSWORD={_quote(db_password)} createdb -h {_quote(db_host)} -p {db_port} -U {_quote(db_user)} -O {_quote(db_user)} {_quote(target_db)}",
                ),
                Command(
                    "Restaurar dump en DB destino",
                    f"PGPASSWORD={_quote(db_password)} pg_restore -h {_quote(db_host)} -p {db_port} -U {_quote(db_user)} -d {_quote(target_db)} --no-owner --no-privileges {_quote(dump_file)}",
                ),
            ]
        )
        commands.extend(
            _post_db_mode_commands(
                db_host=db_host,
                db_port=db_port,
                db_user=db_user,
                db_password=db_password,
                target_db=target_db,
                migration_mode=migration_mode,
                neutralize=neutralize,
            )
        )

    if restore_mode in {"Solo Filestore", "DB + Filestore"}:
        print("Selecciona archivo backup de filestore (.tar.gz)")
        filestore_backup = select_file_path(".")
        target_filestore = _filestore_path(config, target_db)
        overwrite_store = False
        if path_exists(target_filestore):
            overwrite_store = ask_bool(
                "El filestore destino existe, ¿sobrescribir?", False
            )
            if not overwrite_store:
                print("[INFO] Restauración de filestore cancelada por conflicto.")
                return

        commands.append(
            Command(
                "Crear ruta base de filestore", f"mkdir -p {_quote(target_filestore)}"
            )
        )
        if overwrite_store:
            commands.append(
                Command(
                    "Eliminar filestore previo", f"rm -rf {_quote(target_filestore)}/*"
                )
            )
        commands.append(
            Command(
                "Restaurar filestore en destino",
                f"tar -xzf {_quote(filestore_backup)} -C {_quote(target_filestore)}",
            )
        )

    if not confirm_with_phrase(
        "Acción sensible de restauración detectada.",
        f"RESTORE {config.instance}",
    ):
        print("[INFO] Confirmación no válida. Operación cancelada.")
        return

    _execute_plan(commands)


def _duplicate_instance(config: InstanceConfig) -> None:
    source_db = _select_db_name(
        config.instance, "DB origen para duplicar", required=True
    )
    if not source_db:
        print("[INFO] Sin DB origen, operación cancelada.")
        return

    target_instance = ask_text("Nueva instancia destino", "", required=True)
    target_db = ask_text("Nueva DB destino", target_instance, required=True)

    target_config = InstanceConfig(instance=target_instance)
    target_config.db_user = target_db
    try:
        target_config.validate_identifiers()
    except ValueError as error:
        print(level_text("ERROR", str(error)))
        return
    if path_exists(target_config.odoo_home):
        print(f"[ERROR] Ya existe {target_config.odoo_home}")
        return
    if service_exists(target_instance):
        print(f"[ERROR] Ya existe servicio systemd: {target_instance}")
        return
    if database_exists(target_db):
        print(f"[ERROR] Ya existe DB destino: {target_db}")
        return

    db_host = ask_text("DB server", "127.0.0.1", required=True)
    db_port = ask_int("DB port", 5432)
    db_user = ask_text("DB user", config.instance, required=True)
    db_password = ask_text("DB password", None, required=True)

    migration_mode = choose(
        "Modo de duplicación",
        ["Copiada (nuevo UUID en destino)", "Movida (mantener UUID)"],
        default_index=None,
    )
    if not migration_mode:
        print("[INFO] Operación cancelada.")
        return
    neutralize = ask_bool("¿Neutralizar DB duplicada?", True)
    duplicate_filestore = ask_bool("¿Duplicar también filestore?", True)

    commands: list[Command] = [
        Command(
            "Duplicar DB por plantilla",
            f"PGPASSWORD={_quote(db_password)} createdb -h {_quote(db_host)} -p {db_port} -U {_quote(db_user)} -T {_quote(source_db)} -O {_quote(db_user)} {_quote(target_db)}",
        )
    ]

    commands.extend(
        _post_db_mode_commands(
            db_host=db_host,
            db_port=db_port,
            db_user=db_user,
            db_password=db_password,
            target_db=target_db,
            migration_mode=migration_mode,
            neutralize=neutralize,
        )
    )

    if duplicate_filestore:
        source_filestore = _filestore_path(config, source_db)
        # Target filestore must resolve under the TARGET instance's data dir, not
        # the source instance's, or the duplicated instance starts without it.
        target_filestore = _filestore_path(target_config, target_db)
        if path_exists(target_filestore):
            print(f"[ERROR] Ya existe filestore destino: {target_filestore}")
            return

        target_parent = target_filestore.rsplit("/", 1)[0]
        commands.extend(
            [
                Command(
                    "Crear ruta base filestore destino",
                    f"mkdir -p {_quote(target_parent)}",
                ),
                Command(
                    "Duplicar filestore",
                    f"cp -a {_quote(source_filestore)} {_quote(target_filestore)}",
                ),
            ]
        )

    if not confirm_with_phrase(
        "Acción sensible de duplicación detectada.",
        f"DUPLICAR {config.instance}",
    ):
        print("[INFO] Confirmación no válida. Operación cancelada.")
        return

    _execute_plan(commands)


def _delete_instance(config: InstanceConfig) -> None:
    drop_db = ask_bool("¿Eliminar también base de datos?", False)
    remove_store = ask_bool("¿Eliminar también filestore?", False)

    db_name = ""
    db_host = ""
    db_port = 5432
    db_user = ""
    db_password = ""

    if drop_db:
        db_name = ask_text("DB a eliminar", config.instance, required=True)
        db_host = ask_text("DB server", "127.0.0.1", required=True)
        db_port = ask_int("DB port", 5432)
        db_user = ask_text("DB user", config.instance, required=True)
        db_password = ask_text("DB password", None, required=True)

    commands: list[Command] = [
        Command(
            "Detener servicio Odoo",
            f"systemctl stop {_quote(config.odoo_service)} || true",
        ),
        Command(
            "Deshabilitar servicio Odoo",
            f"systemctl disable {_quote(config.odoo_service)} || true",
        ),
        Command(
            "Eliminar unit file",
            f"rm -f {_quote(f'/etc/systemd/system/{config.odoo_service}.service')}",
        ),
        Command("Recargar systemd", "systemctl daemon-reload"),
        Command(
            "Eliminar configuración Odoo", f"rm -rf {_quote(config.odoo_conf_dir)}"
        ),
        Command("Eliminar home de instancia", f"rm -rf {_quote(config.odoo_home)}"),
        Command(
            "Eliminar Nginx HTTP",
            f"rm -f {_quote(f'/etc/nginx/sites-available/{config.nginx_http_name}')} {_quote(f'/etc/nginx/sites-enabled/{config.nginx_http_name}')}",
        ),
        Command(
            "Eliminar Nginx HTTPS",
            f"rm -f {_quote(f'/etc/nginx/sites-available/{config.nginx_https_name}')} {_quote(f'/etc/nginx/sites-enabled/{config.nginx_https_name}')}",
        ),
        Command("Eliminar SSL de instancia", f"rm -rf {_quote(config.nginx_ssl_dir)}"),
        Command("Validar Nginx", "nginx -t"),
        Command("Recargar Nginx", "systemctl reload nginx || true"),
    ]

    if drop_db and db_name:
        commands.append(
            Command(
                "Eliminar DB",
                f"PGPASSWORD={_quote(db_password)} dropdb -h {_quote(db_host)} -p {db_port} -U {_quote(db_user)} {_quote(db_name)}",
            )
        )

    if remove_store:
        store_db = ask_text(
            "Filestore DB a eliminar", db_name or config.instance, required=True
        )
        if not _is_safe_path_component(store_db):
            print(
                level_text(
                    "ERROR",
                    "Nombre de DB de filestore no válido (no se permiten '/', '..' ni nombres reservados).",
                )
            )
            return
        commands.append(
            Command(
                "Eliminar filestore",
                f"rm -rf {_quote(_filestore_path(config, store_db))}",
            )
        )

    if not confirm_with_phrase(
        "Acción destructiva detectada.",
        f"ELIMINAR {config.instance}",
    ):
        print("[INFO] Confirmación no válida. Operación cancelada.")
        return

    _execute_plan(commands)


def _resolve_db_admin_access() -> tuple[str, str, int, str, str] | None:
    db_host = ask_text("DB server para eliminación total", "127.0.0.1", required=True)
    db_port = ask_int("DB port", 5432)

    if db_host in {"127.0.0.1", "localhost", "::1"}:
        local_probe = run(
            'sudo -u postgres psql -d postgres -tAc "SELECT 1;"',
            check=False,
        )
        if local_probe.returncode == 0 and "1" in local_probe.stdout:
            print("[OK] Acceso admin local a PostgreSQL detectado (sudo -u postgres).")
            return ("local", db_host, db_port, "", "")
        print("[WARN] No fue posible usar sudo -u postgres en este servidor.")

    print("[INFO] Intentaremos conexión admin con usuario/contraseña en el servidor DB.")
    db_admin_user = ask_text("DB admin user", "postgres", required=True)
    db_admin_password = ask_text("DB admin password", None, required=True)

    probe_cmd = (
        f"PGPASSWORD={_quote(db_admin_password)} psql -h {_quote(db_host)} -p {db_port} "
        f"-U {_quote(db_admin_user)} -d postgres -tAc \"SELECT 1;\""
    )
    probe = run(probe_cmd, check=False)
    if probe.returncode == 0 and "1" in probe.stdout:
        print("[OK] Conexión admin remota validada.")
        return ("remote", db_host, db_port, db_admin_user, db_admin_password)

    detail = probe.stderr.strip() or probe.stdout.strip() or "sin detalle"
    print(f"[ERROR] No se pudo conectar al servidor DB con credenciales admin: {detail}")
    print(
        "[INFO] Debes permitir la conexión al servidor PostgreSQL y usar un usuario con permisos completos (superuser/admin)."
    )
    return None


def _db_admin_psql_command(
    session: tuple[str, str, int, str, str], sql: str, psql_flags: str = ""
) -> str:
    mode, db_host, db_port, db_admin_user, db_admin_password = session
    flags = f"{psql_flags} " if psql_flags else ""
    if mode == "local":
        return f"sudo -u postgres psql -v ON_ERROR_STOP=1 -d postgres {flags}-c {shlex.quote(sql)}"

    return (
        f"PGPASSWORD={_quote(db_admin_password)} psql -v ON_ERROR_STOP=1 -h {_quote(db_host)} -p {db_port} "
        f"-U {_quote(db_admin_user)} -d postgres {flags}-c {shlex.quote(sql)}"
    )


def _db_admin_dropdb_command(session: tuple[str, str, int, str, str], db_name: str) -> str:
    mode, db_host, db_port, db_admin_user, db_admin_password = session
    if mode == "local":
        return f"sudo -u postgres dropdb --if-exists {_quote(db_name)}"

    return (
        f"PGPASSWORD={_quote(db_admin_password)} dropdb --if-exists -h {_quote(db_host)} -p {db_port} "
        f"-U {_quote(db_admin_user)} {_quote(db_name)}"
    )


def _list_instance_databases(
    instance: str,
    session: tuple[str, str, int, str, str],
) -> tuple[list[str], str | None]:
    instance_literal = _sql_literal(instance)
    sql = (
        "SELECT datname "
        "FROM pg_database "
        "WHERE datistemplate = false "
        f"AND datname LIKE '{instance_literal}%' "
        "ORDER BY datname;"
    )
    query_cmd = _db_admin_psql_command(session, sql, psql_flags="-tA")
    result = run(query_cmd, check=False)
    if result.returncode != 0:
        error_text = result.stderr.strip() or result.stdout.strip() or "Error desconocido"
        return [], error_text

    rows = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return rows, None


def _list_filestore_databases(config: InstanceConfig) -> tuple[list[str], str]:
    filestore_root = f"{_resolve_data_dir(config)}/filestore"
    if not os.path.isdir(filestore_root):
        return [], filestore_root

    db_names = sorted(
        [
            entry
            for entry in os.listdir(filestore_root)
            if os.path.isdir(os.path.join(filestore_root, entry)) and not entry.startswith(".")
        ]
    )
    return db_names, filestore_root


def purge_instance_superuser() -> None:
    instance = _select_existing_instance()
    if not instance:
        print("[INFO] Operación cancelada.")
        return

    config = _validate_instance_or_abort(instance)
    if config is None:
        return

    filestore_dbs, filestore_root = _list_filestore_databases(config)

    session = _resolve_db_admin_access()
    db_names: list[str] = list(filestore_dbs)
    dbs_by_prefix: list[str] = []
    db_error: str | None = None
    if session:
        dbs_by_prefix, db_error = _list_instance_databases(instance, session)
        if db_error:
            print(f"[WARN] No se pudieron detectar DBs por prefijo '{instance}': {db_error}")
        for db_name in dbs_by_prefix:
            if db_name not in db_names:
                db_names.append(db_name)
    else:
        print(
            "[WARN] Se continuará con limpieza local (servicio/config/store). El borrado de DB/roles se omite por falta de conexión admin al servidor DB."
        )

    manual_dbs = ask_text(
        "DBs extra a eliminar (coma, opcional)",
        "",
        required=False,
    )
    if manual_dbs:
        for item in [name.strip() for name in manual_dbs.split(",") if name.strip()]:
            if item not in db_names:
                db_names.append(item)

    if db_names:
        print("\nDBs candidatas para eliminación:")
        for name in db_names:
            print(f"- {name}")
    else:
        print("[INFO] No hay DBs detectadas/indicadas para eliminar.")

    commands: list[Command] = [
        Command(
            "Detener servicio Odoo",
            f"systemctl stop {_quote(config.odoo_service)} || true",
        ),
        Command(
            "Deshabilitar servicio Odoo",
            f"systemctl disable {_quote(config.odoo_service)} || true",
        ),
        Command(
            "Eliminar unit file",
            f"rm -f {_quote(f'/etc/systemd/system/{config.odoo_service}.service')}",
        ),
        Command("Recargar systemd", "systemctl daemon-reload"),
        Command(
            "Eliminar configuración Odoo", f"rm -rf {_quote(config.odoo_conf_dir)}"
        ),
        Command("Eliminar home de instancia", f"rm -rf {_quote(config.odoo_home)}"),
        Command(
            "Eliminar usuario Linux de instancia",
            f"id -u {_quote(config.odoo_user)} >/dev/null 2>&1 && userdel -r {_quote(config.odoo_user)} || true",
        ),
        Command(
            "Eliminar logs Odoo/Nginx de instancia",
            f"rm -f {_quote(f'/var/log/odoo/{config.instance}.log')} {_quote(f'/var/log/nginx/{config.instance}.access.log')} {_quote(f'/var/log/nginx/{config.instance}.error.log')}",
        ),
        Command(
            "Eliminar Nginx HTTP",
            f"rm -f {_quote(f'/etc/nginx/sites-available/{config.nginx_http_name}')} {_quote(f'/etc/nginx/sites-enabled/{config.nginx_http_name}')}",
        ),
        Command(
            "Eliminar Nginx HTTPS",
            f"rm -f {_quote(f'/etc/nginx/sites-available/{config.nginx_https_name}')} {_quote(f'/etc/nginx/sites-enabled/{config.nginx_https_name}')}",
        ),
        Command("Eliminar SSL de instancia", f"rm -rf {_quote(config.nginx_ssl_dir)}"),
        Command("Eliminar raíz filestore de instancia", f"rm -rf {_quote(filestore_root)}"),
        Command("Validar/recargar Nginx (best effort)", "nginx -t && systemctl reload nginx || true"),
    ]

    if session:
        for db_name in db_names:
            db_literal = _sql_literal(db_name)
            terminate_sql = (
                "SELECT pg_terminate_backend(pid) "
                "FROM pg_stat_activity "
                f"WHERE datname = '{db_literal}' AND pid <> pg_backend_pid();"
            )
            commands.append(
                Command(
                    f"Cerrar conexiones activas de DB {db_name}",
                    _db_admin_psql_command(session, terminate_sql) + " || true",
                )
            )
            commands.append(
                Command(
                    f"Eliminar DB {db_name}",
                    _db_admin_dropdb_command(session, db_name),
                )
            )

        role_candidates = [config.instance, config.db_user]
        unique_roles: list[str] = []
        for role in role_candidates:
            if role and role not in unique_roles:
                unique_roles.append(role)

        for role in unique_roles:
            drop_role_sql = f"DROP ROLE IF EXISTS {role};"
            commands.append(
                Command(
                    f"Eliminar rol PostgreSQL {role} (si existe)",
                    _db_admin_psql_command(session, drop_role_sql) + " || true",
                )
            )

    print(f"\n{title('Resumen de eliminación total')}")
    summary_rows = [
        ["Instancia", instance],
        ["Servicio systemd detectado", "sí" if service_exists(config.odoo_service) else "no"],
        ["Home de instancia detectado", "sí" if path_exists(config.odoo_home) else "no"],
        ["Configuración detectada", "sí" if path_exists(config.odoo_conf_dir) else "no"],
        ["Nginx HTTP detectado", "sí" if path_exists(f"/etc/nginx/sites-available/{config.nginx_http_name}") else "no"],
        ["Nginx HTTPS detectado", "sí" if path_exists(f"/etc/nginx/sites-available/{config.nginx_https_name}") else "no"],
        ["SSL detectado", "sí" if path_exists(config.nginx_ssl_dir) else "no"],
        ["Filestore raíz detectado", f"{'sí' if path_exists(filestore_root) else 'no'} ({filestore_root})"],
        ["DBs por filestore", ", ".join(filestore_dbs) if filestore_dbs else "(ninguna)"],
        ["DBs por prefijo", ", ".join(dbs_by_prefix) if dbs_by_prefix else "(ninguna)"],
        ["Acceso admin DB", session[0] if session else "no disponible (solo limpieza local)"],
        ["DBs a eliminar", ", ".join(db_names) if db_names else "(ninguna detectada)"],
        ["Comandos a ejecutar", str(len(commands))],
    ]
    print(render_table(["Campo", "Valor"], summary_rows))

    if not confirm_with_phrase(
        "Acción SUPER destructiva detectada.",
        f"ELIMINAR-TODO {instance}",
    ):
        print("[INFO] Confirmación no válida. Operación cancelada.")
        return

    _execute_plan(commands)


def manage_existing_instance() -> None:
    instance = _select_existing_instance()
    if not instance:
        print("[INFO] Operación cancelada.")
        return

    config = _validate_instance_or_abort(instance)
    if config is None:
        return

    config.db_name, db_error, listed_dbs = _probe_databases_for_management(instance)

    while True:
        print("\nEstado completo de la instancia:")
        _show_instance_status(config, db_error=db_error, listed_dbs=listed_dbs)

        action = choose(
            f"\nGestión segura de instancia: {instance}",
            [
                "Consultar ubicaciones/config actual",
                "Actualizar configuración existente",
                "Reparar logs Nginx de instancia",
                "Instalar paquetes Python en venv",
                "Realizar backup",
                "Restaurar backup",
                "Duplicar instancia",
                "Eliminar instancia",
                "Volver",
            ],
            default_index=None,
        )

        if action in {"", "Volver"}:
            return

        if action == "Consultar ubicaciones/config actual":
            _show_instance_locations(config)
        elif action == "Actualizar configuración existente":
            update_existing_configs(instance)
            config = InstanceConfig(instance=instance)
            config.db_name, db_error, listed_dbs = _probe_databases_for_management(
                instance
            )
            config.normalize_defaults()
        elif action == "Reparar logs Nginx de instancia":
            _repair_instance_nginx_logs(config)
        elif action == "Instalar paquetes Python en venv":
            _install_python_packages_in_instance_venv(config)
        elif action == "Realizar backup":
            _backup_instance(config)
        elif action == "Restaurar backup":
            _restore_backup(config)
        elif action == "Duplicar instancia":
            _duplicate_instance(config)
        elif action == "Eliminar instancia":
            _delete_instance(config)


def _command_output(command: str) -> str:
    result = run(command, check=False)
    if result.returncode != 0:
        return ""
    return (result.stdout or result.stderr).strip()


def _read_text_file(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as file_handle:
            return file_handle.read()
    except OSError:
        return ""


def _collect_system_overview() -> list[list[str]]:
    hostname = socket.gethostname()
    os_release = _read_text_file("/etc/os-release")
    pretty_name = ""
    for line in os_release.splitlines():
        if line.startswith("PRETTY_NAME="):
            pretty_name = line.split("=", 1)[1].strip().strip('"')
            break

    rows = [
        ["Hostname", hostname],
        ["SO", pretty_name or "no detectado"],
        ["Kernel", _command_output("uname -r") or "no detectado"],
        ["Arquitectura", _command_output("uname -m") or "no detectada"],
        ["Virtualización", _command_output("systemd-detect-virt") or "no detectada"],
        ["Uptime", _command_output("uptime -p") or "no detectado"],
        ["IP(s)", _command_output("hostname -I") or "no detectadas"],
        ["Python3 (sistema)", _command_output("python3 --version") or "no detectado"],
        ["Python3 path", _command_output("command -v python3") or "no detectado"],
        ["PostgreSQL client", _command_output("psql --version") or "no detectado"],
        ["Nginx", _command_output("nginx -v 2>&1") or "no detectado"],
    ]
    return rows


def _list_odoo_service_names() -> list[str]:
    service_lines = _command_output(
        "systemctl list-unit-files --type=service --no-legend --no-pager | awk '{print $1}'"
    )
    if not service_lines:
        return []

    services: list[str] = []
    for unit in service_lines.splitlines():
        service = unit.strip()
        if not service.endswith(".service"):
            continue
        unit_content = _command_output(f"systemctl cat {_quote(service)} 2>/dev/null")
        if "odoo-bin" in unit_content or "Description=Odoo" in unit_content:
            services.append(service[:-8])

    return sorted(set(services))


def _safe_find_paths(
    roots: list[str],
    entry_type: str,
    pattern: str,
    max_depth: int = 6,
    max_items: int = 300,
) -> list[str]:
    existing_roots = [root for root in roots if os.path.isdir(root)]
    if not existing_roots:
        return []

    roots_expr = " ".join(_quote(root) for root in existing_roots)
    cmd = (
        f"find {roots_expr} -maxdepth {max_depth} -type {entry_type} -iname {shlex.quote(pattern)} "
        f"2>/dev/null | head -n {max_items}"
    )
    output = _command_output(cmd)
    if not output:
        return []
    return sorted(set(line.strip() for line in output.splitlines() if line.strip()))


def _is_backup_like_name(name: str) -> bool:
    lowered = name.lower()
    markers = ["bak", "backup", "old", "orig", "save", "disabled", "~", ".dpkg-"]
    return any(marker in lowered for marker in markers)


def _is_valid_odoo_conf_file(path: str) -> bool:
    if not path or not os.path.isfile(path):
        return False

    if _is_backup_like_name(os.path.basename(path)):
        return False

    values = read_odoo_conf(path)
    if not values:
        return False

    expected_keys = {
        "addons_path",
        "http_port",
        "gevent_port",
        "db_host",
        "db_port",
        "db_user",
        "admin_passwd",
        "data_dir",
    }
    return len([key for key in expected_keys if key in values]) >= 2


def _discover_odoo_named_directories() -> list[str]:
    return _safe_find_paths(["/etc", "/opt", "/srv", "/home", "/var/lib"], "d", "*odoo*", max_depth=6)


def _discover_nginx_odoo_paths(service_names: list[str]) -> list[str]:
    paths: set[str] = set()
    nginx_dirs = ["/etc/nginx/sites-available", "/etc/nginx/sites-enabled"]
    for nginx_dir in nginx_dirs:
        if not os.path.isdir(nginx_dir):
            continue

        for name in sorted(os.listdir(nginx_dir)):
            file_path = os.path.join(nginx_dir, name)
            if os.path.islink(file_path):
                file_path = os.path.realpath(file_path)
            if not os.path.isfile(file_path):
                continue

            if _is_backup_like_name(os.path.basename(file_path)):
                continue

            content = _read_text_file(file_path).lower()
            if not content:
                continue

            if "odoo" in content or "odoochat" in content:
                paths.add(file_path)
                continue

            if "proxy_pass" in content and "server_name" in content and "127.0.0.1:" in content:
                paths.add(file_path)
                continue

            for service_name in service_names:
                if service_name.lower() in content:
                    paths.add(file_path)
                    break

    return sorted(paths)


def _discover_filestore_roots(
    service_names: list[str],
    conf_paths: list[str],
) -> list[str]:
    roots: set[str] = set()

    for conf_path in conf_paths:
        values = read_odoo_conf(conf_path)
        data_dir = values.get("data_dir", "").strip()
        if data_dir:
            roots.add(f"{data_dir}/filestore")

    for service_name in service_names:
        execstart = _parse_service_execstart(service_name)
        odoo_home = _extract_odoo_home_from_execstart(execstart)
        if odoo_home:
            roots.add(f"{odoo_home}/.local/share/Odoo/filestore")
        roots.add(f"/opt/odoo/{service_name}/.local/share/Odoo/filestore")

    for path in _safe_find_paths(["/opt", "/srv", "/home", "/var/lib"], "d", "filestore", max_depth=7):
        if "/.ssh/" in path or path.endswith("/.ssh/filestore"):
            continue
        roots.add(path)

    existing = [
        path
        for path in sorted(roots)
        if os.path.isdir(path) and "/.ssh/" not in path and not path.endswith("/.ssh/filestore")
    ]
    return existing


def _cell_multiline(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    return text.replace(", ", ",\n")


def _guess_instance_from_conf_path(conf_path: str) -> str:
    match = re.search(r"/etc/odoo/([^/]+)/[^/]+\.conf$", conf_path)
    if match:
        return match.group(1)

    match = re.search(r"/etc/([^/]+)/odoo\.conf$", conf_path)
    if match:
        return match.group(1)

    file_name = os.path.basename(conf_path)
    lower_file = file_name.lower()
    if lower_file.startswith("odoo") and lower_file.endswith(".conf") and not _is_backup_like_name(lower_file):
        return file_name[:-5]

    base = os.path.basename(os.path.dirname(conf_path))
    if base and base not in {"etc", "filter.d", "sites-available", "sites-enabled"}:
        return base
    return ""


def _parse_service_execstart(service_name: str) -> str:
    unit_content = _command_output(
        f"systemctl cat {_quote(service_name + '.service')} 2>/dev/null"
    )
    for raw_line in unit_content.splitlines():
        line = raw_line.strip()
        if line.startswith("ExecStart="):
            return line.split("=", 1)[1].strip()
    return ""


def _extract_python_from_execstart(execstart: str) -> str:
    if not execstart:
        return ""
    parts = shlex.split(execstart)
    if not parts:
        return ""
    candidate = parts[0]
    return candidate if os.path.exists(candidate) else ""


def _extract_odoo_home_from_execstart(execstart: str) -> str:
    if not execstart:
        return ""
    parts = shlex.split(execstart)
    for idx, token in enumerate(parts):
        if token.endswith("odoo-bin"):
            if token.endswith("/odoo/odoo-bin"):
                return token[: -len("/odoo/odoo-bin")]
            if token.endswith("/odoo-bin"):
                return token[: -len("/odoo-bin")]
            return os.path.dirname(token)
        if token == "-c" and idx + 1 < len(parts):
            conf_path = parts[idx + 1]
            values = read_odoo_conf(conf_path)
            addons = values.get("addons_path", "")
            if addons:
                first = addons.split(",", 1)[0]
                suffix = "/odoo/addons"
                if first.endswith(suffix):
                    return first[: -len(suffix)]
    return ""


def _extract_conf_from_execstart(execstart: str) -> str:
    if not execstart:
        return ""
    parts = shlex.split(execstart)
    for idx, token in enumerate(parts):
        if token == "-c" and idx + 1 < len(parts):
            return parts[idx + 1]
        if token.startswith("--config="):
            return token.split("=", 1)[1]
    return ""


def _collect_service_contexts() -> list[dict[str, str]]:
    contexts: list[dict[str, str]] = []
    for service_name in _list_odoo_service_names():
        execstart = _parse_service_execstart(service_name)
        python_path = _extract_python_from_execstart(execstart)
        odoo_home = _extract_odoo_home_from_execstart(execstart)
        conf_hint = _extract_conf_from_execstart(execstart)
        if not conf_hint:
            for default_conf in _odoo_conf_candidates(service_name):
                if os.path.isfile(default_conf):
                    conf_hint = default_conf
                    break

        contexts.append(
            {
                "service": service_name,
                "execstart": execstart,
                "python_path": python_path,
                "odoo_home": odoo_home,
                "conf_hint": conf_hint,
            }
        )
    return contexts


def _discover_odoo_conf_paths_from_contexts(
    contexts: list[dict[str, str]],
) -> list[str]:
    conf_paths: set[str] = set()

    for context in contexts:
        service_name = context.get("service", "")
        conf_hint = context.get("conf_hint", "")
        odoo_home = context.get("odoo_home", "")
        python_path = context.get("python_path", "")

        if conf_hint and _is_valid_odoo_conf_file(conf_hint):
            conf_paths.add(conf_hint)

        focused_roots: set[str] = set()
        if service_name:
            focused_roots.add(f"/etc/{service_name}")
            focused_roots.add(f"/etc/odoo/{service_name}")
        if conf_hint:
            focused_roots.add(os.path.dirname(conf_hint))
        if odoo_home:
            focused_roots.add(odoo_home)
            focused_roots.add(f"{odoo_home}/odoo")
        if python_path:
            focused_roots.add(os.path.dirname(python_path))
            focused_roots.add(os.path.dirname(os.path.dirname(python_path)))

        roots = [root for root in sorted(focused_roots) if root and os.path.isdir(root)]
        if roots:
            for path in _safe_find_paths(roots, "f", "*.conf", max_depth=5, max_items=80):
                if _is_valid_odoo_conf_file(path):
                    conf_paths.add(path)
            for path in _safe_find_paths(roots, "f", "odoo.conf", max_depth=5, max_items=60):
                if _is_valid_odoo_conf_file(path):
                    conf_paths.add(path)
            for path in _safe_find_paths(roots, "f", "*odoo*.conf", max_depth=5, max_items=80):
                if _is_valid_odoo_conf_file(path):
                    conf_paths.add(path)

    if not conf_paths:
        fallback_roots: list[str] = []
        if os.path.isdir("/etc/odoo"):
            fallback_roots.append("/etc/odoo")

        for name in sorted(os.listdir("/etc")) if os.path.isdir("/etc") else []:
            path = f"/etc/{name}"
            if os.path.isdir(path) and "odoo" in name.lower():
                fallback_roots.append(path)

        fallback_roots.append("/etc")

        if os.path.isdir("/etc/odoo"):
            for path in _safe_find_paths(["/etc/odoo"], "f", "*.conf", max_depth=6, max_items=300):
                if _is_valid_odoo_conf_file(path):
                    conf_paths.add(path)
        for path in _safe_find_paths(fallback_roots, "f", "odoo.conf", max_depth=6, max_items=200):
            if _is_valid_odoo_conf_file(path):
                conf_paths.add(path)
        for path in _safe_find_paths(fallback_roots, "f", "*odoo*.conf", max_depth=6, max_items=250):
            if _is_valid_odoo_conf_file(path):
                conf_paths.add(path)

    return sorted(conf_paths)


def _parse_nginx_tls_metadata(path: str) -> tuple[str, str, str]:
    content = _read_text_file(path)
    if not content:
        return "", "", ""

    server_name = ""
    cert_path = ""
    key_path = ""
    for raw_line in content.splitlines():
        line = raw_line.strip().rstrip(";")
        if line.startswith("server_name ") and not server_name:
            server_name = line.split(maxsplit=1)[1].strip()
        elif line.startswith("ssl_certificate ") and not cert_path:
            cert_path = line.split(maxsplit=1)[1].strip()
        elif line.startswith("ssl_certificate_key ") and not key_path:
            key_path = line.split(maxsplit=1)[1].strip()
    return server_name, cert_path, key_path


def _certificate_metadata(cert_path: str) -> dict[str, str]:
    if not cert_path or not path_exists(cert_path):
        return {"issuer": "", "subject": "", "not_after": "", "serial": ""}

    result = run(
        f"openssl x509 -in {_quote(cert_path)} -noout -issuer -subject -enddate -serial",
        check=False,
    )
    if result.returncode != 0:
        return {"issuer": "", "subject": "", "not_after": "", "serial": ""}

    issuer = ""
    subject = ""
    not_after = ""
    serial = ""
    for line in result.stdout.splitlines():
        raw = line.strip()
        if raw.startswith("issuer="):
            issuer = raw[len("issuer=") :].strip()
        elif raw.startswith("subject="):
            subject = raw[len("subject=") :].strip()
        elif raw.startswith("notAfter="):
            not_after = raw[len("notAfter=") :].strip()
        elif raw.startswith("serial="):
            serial = raw[len("serial=") :].strip()

    return {
        "issuer": issuer,
        "subject": subject,
        "not_after": not_after,
        "serial": serial,
    }


def _certificate_expiry_status(cert_path: str, threshold_days: int) -> tuple[str, str]:
    if not cert_path or not path_exists(cert_path):
        return "MISSING", "certificado no encontrado"

    result = run(
        f"openssl x509 -in {_quote(cert_path)} -noout -checkend {threshold_days * 86400}",
        check=False,
    )
    if result.returncode == 0:
        return "OK", f"vigente > {threshold_days} días"

    enddate = run(
        f"openssl x509 -in {_quote(cert_path)} -noout -enddate",
        check=False,
    )
    expires_text = ""
    if enddate.returncode == 0 and enddate.stdout.strip().startswith("notAfter="):
        expires_text = enddate.stdout.strip().split("=", 1)[1].strip()

    if expires_text:
        return "WARN", f"caduca antes de {threshold_days} días ({expires_text})"
    return "ERROR", "no se pudo validar expiración"


def _list_local_postgres_databases(instance: str, db_user: str) -> list[str]:
    instance_literal = _sql_literal(instance)
    db_user_literal = _sql_literal(db_user)
    sql = (
        "SELECT datname "
        "FROM pg_database d "
        "JOIN pg_roles r ON d.datdba = r.oid "
        "WHERE d.datistemplate = false "
        f"AND (d.datname LIKE '{instance_literal}%' OR r.rolname = '{db_user_literal}') "
        "ORDER BY d.datname;"
    )
    result = run(
        f"sudo -u postgres psql -d postgres -tA -c {shlex.quote(sql)}",
        check=False,
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _detect_tls_cert_type(cert_path: str, key_path: str) -> str:
    if not cert_path and not key_path:
        return "sin TLS"
    if "/etc/letsencrypt/" in cert_path or "/etc/letsencrypt/" in key_path:
        return "Let's Encrypt"
    if cert_path and _is_self_signed_certificate(cert_path):
        return "Autofirmado"
    if cert_path and key_path:
        return "Personalizado"
    return "TLS incompleto"


def _nginx_matches_instance(
    content: str,
    instance: str,
    service_name: str,
    http_port: str,
    gevent_port: str,
    conf_path: str,
    data_dir: str,
) -> bool:
    lower = content.lower()
    tokens = [
        instance.lower(),
        service_name.lower(),
        conf_path.lower(),
        data_dir.lower(),
    ]
    for token in tokens:
        if token and token in lower:
            return True

    if http_port.isdigit() and f":{http_port}" in lower:
        return True
    if gevent_port.isdigit() and f":{gevent_port}" in lower:
        return True

    return False


def _detect_odoo_release_version(odoo_home: str) -> str:
    if not odoo_home:
        return ""
    release_path = f"{odoo_home}/odoo/odoo/release.py"
    content = _read_text_file(release_path)
    if not content:
        return ""

    version_line = ""
    for line in content.splitlines():
        if line.strip().startswith("version_info"):
            version_line = line
            break
    if not version_line:
        return ""

    match = re.search(r"\((\d+),\s*(\d+)", version_line)
    if match:
        return f"{match.group(1)}.{match.group(2)}"
    return ""


def _collect_external_instance_rows(
    service_contexts: list[dict[str, str]],
    conf_paths: list[str],
    nginx_paths: list[str],
    filestore_roots: list[str],
) -> list[list[str]]:
    service_names = [context.get("service", "") for context in service_contexts if context.get("service")]
    service_context_by_name = {
        context.get("service", ""): context
        for context in service_contexts
        if context.get("service")
    }

    detected: set[str] = set(list_instances(InstanceConfig.base_instances_dir))
    detected.update(service_names)
    for conf_path in conf_paths:
        guessed = _guess_instance_from_conf_path(conf_path)
        if guessed:
            detected.add(guessed)

    filestore_db_map: dict[str, set[str]] = {}
    for root in filestore_roots:
        db_names: set[str] = set()
        if os.path.isdir(root):
            try:
                for name in os.listdir(root):
                    if os.path.isdir(os.path.join(root, name)) and not name.startswith("."):
                        db_names.add(name)
            except OSError:
                pass
        filestore_db_map[root] = db_names

    rows: list[list[str]] = []
    for instance in sorted(detected):
        config = InstanceConfig(instance=instance)
        config.normalize_defaults()

        service_state = level_text("OK", "activo") if service_active(config.odoo_service) else level_text("MISSING", "detenido")
        autostart_state = level_text("OK", "sí") if service_enabled(config.odoo_service) else level_text("INFO", "no")

        instance_conf_paths = [
            path
            for path in conf_paths
            if f"/{instance}/" in path or path.endswith(f"/{instance}.conf") or f"/{instance}-" in path
        ]
        preferred_conf = config.odoo_conf_file if path_exists(config.odoo_conf_file) else (instance_conf_paths[0] if instance_conf_paths else "")
        conf_values = read_odoo_conf(preferred_conf) if preferred_conf else {}
        http_port = conf_values.get("http_port", "") or ""
        gevent_port = conf_values.get("gevent_port", "") or ""
        db_port = conf_values.get("db_port", "") or ""
        db_host = conf_values.get("db_host", "") or ""
        db_user = conf_values.get("db_user", "") or config.db_user
        addons_path = conf_values.get("addons_path", "") or ""
        workers = conf_values.get("workers", "") or ""
        data_dir = conf_values.get("data_dir", "").strip() if conf_values else ""
        if not data_dir:
            data_dir = f"{config.odoo_home}/.local/share/Odoo"
        filestore_root = f"{data_dir}/filestore"

        filestore_dbs: list[str] = []
        if os.path.isdir(filestore_root):
            filestore_dbs = sorted(
                [
                    name
                    for name in os.listdir(filestore_root)
                    if os.path.isdir(os.path.join(filestore_root, name)) and not name.startswith(".")
                ]
            )

        local_db_names: list[str] = []
        if _is_local_db_host(db_host):
            local_db_names = _list_local_postgres_databases(instance, db_user)
        local_db_set = set(local_db_names)

        context = service_context_by_name.get(config.odoo_service, {})
        python_path = context.get("python_path", "")
        python_version = _command_output(f"{_quote(python_path)} --version") if python_path else ""
        odoo_home = context.get("odoo_home", "") or config.odoo_home
        odoo_version = _detect_odoo_release_version(odoo_home)

        nginx_hits: list[str] = []
        for path in nginx_paths:
            content = _read_text_file(path)
            if not content:
                continue
            if _nginx_matches_instance(
                content=content,
                instance=instance,
                service_name=config.odoo_service,
                http_port=http_port,
                gevent_port=gevent_port,
                conf_path=preferred_conf,
                data_dir=data_dir,
            ):
                nginx_hits.append(path)

        if not nginx_hits:
            for path in nginx_paths:
                content = _read_text_file(path)
                if not content:
                    continue
                if "odoo" in content.lower() and (
                    f"/etc/{instance}/" in content.lower() or f"/opt/odoo/{instance}" in content.lower()
                ):
                    nginx_hits.append(path)

        filestore_hits: list[str] = []
        filestore_match_dbs: set[str] = set()
        for root in filestore_roots:
            root_db_names = filestore_db_map.get(root, set())
            if local_db_set and root_db_names.intersection(local_db_set):
                filestore_hits.append(root)
                filestore_match_dbs.update(root_db_names.intersection(local_db_set))
                continue

            if root == filestore_root or root.startswith(filestore_root) or instance in root:
                filestore_hits.append(root)
                filestore_match_dbs.update(root_db_names)

        if local_db_set and not filestore_match_dbs:
            filestore_match_dbs = local_db_set

        filestore_db_summary = ", ".join(sorted(filestore_match_dbs)) if filestore_match_dbs else ", ".join(filestore_dbs[:8])

        cert_candidates: set[str] = set()
        key_candidates: set[str] = set()
        server_name_candidates: set[str] = set()
        for nginx_path in nginx_hits:
            server_name, cert_path, key_path = _parse_nginx_tls_metadata(nginx_path)
            if server_name:
                server_name_candidates.add(server_name)
            if cert_path:
                cert_candidates.add(cert_path)
            if key_path:
                key_candidates.add(key_path)

        cert_summary = ", ".join(sorted(cert_candidates)) if cert_candidates else ""
        key_summary = ", ".join(sorted(key_candidates)) if key_candidates else ""
        server_name_summary = ", ".join(sorted(server_name_candidates)) if server_name_candidates else ""
        tls_type = _detect_tls_cert_type(next(iter(cert_candidates), ""), next(iter(key_candidates), ""))
        cert_meta = _certificate_metadata(next(iter(cert_candidates), ""))

        addons_summary = ""
        if addons_path:
            addon_items = [item.strip() for item in addons_path.split(",") if item.strip()]
            addons_summary = ", ".join(addon_items[:3]) + (" ..." if len(addon_items) > 3 else "")

        rows.append(
            [
                instance,
                service_state,
                autostart_state,
                odoo_version or "no detectada",
                http_port,
                gevent_port,
                db_host,
                db_user,
                db_port,
                workers,
                python_version or "",
                python_path or "",
                preferred_conf or "",
                data_dir,
                filestore_db_summary + (" ..." if len(filestore_match_dbs) > 8 else ""),
                addons_summary,
                server_name_summary,
                cert_summary,
                key_summary,
                tls_type,
                cert_meta.get("issuer", ""),
                cert_meta.get("subject", ""),
                cert_meta.get("not_after", ""),
                cert_meta.get("serial", ""),
                ", ".join(local_db_names),
                str(len(nginx_hits)),
                str(len(filestore_hits)),
            ]
        )

    return rows


def _collect_odoo_services_rows(service_contexts: list[dict[str, str]]) -> list[list[str]]:
    rows: list[list[str]] = []
    for context in service_contexts:
        service_name = context.get("service", "")
        if not service_name:
            continue
        rows.append(
            [
                service_name,
                level_text("OK", "activo") if service_active(service_name) else level_text("MISSING", "detenido"),
                level_text("OK", "sí") if service_enabled(service_name) else level_text("INFO", "no"),
                context.get("python_path", ""),
                context.get("odoo_home", ""),
                context.get("conf_hint", ""),
            ]
        )
    return rows


def external_server_report() -> None:
    print(f"\n{title('Informe para servidor externo')}")

    report_sections: list[str] = []

    service_contexts = _collect_service_contexts()
    service_names = [context.get("service", "") for context in service_contexts if context.get("service")]

    conf_paths = _discover_odoo_conf_paths_from_contexts(service_contexts)
    nginx_paths = _discover_nginx_odoo_paths(service_names)
    filestore_roots = _discover_filestore_roots(service_names, conf_paths)
    named_dirs = _discover_odoo_named_directories()

    system_rows = _collect_system_overview()
    system_rows.extend(
        [
            ["PostgreSQL service", level_text("OK", "activo") if service_active("postgresql") else level_text("MISSING", "detenido")],
            ["PostgreSQL autostart", level_text("OK", "sí") if service_enabled("postgresql") else level_text("INFO", "no")],
            ["Nginx service", level_text("OK", "activo") if service_active("nginx") else level_text("MISSING", "detenido")],
            ["Nginx autostart", level_text("OK", "sí") if service_enabled("nginx") else level_text("INFO", "no")],
            ["Nginx test", _command_output("nginx -t 2>&1 | tail -n 1") or "no disponible"],
        ]
    )
    system_table = render_table(["Campo", "Valor"], system_rows)
    print(f"\n{title('Resumen del servidor')}\n{system_table}")
    report_sections.append("Resumen del servidor\n" + strip_ansi(system_table))

    services_rows = _collect_odoo_services_rows(service_contexts)
    services_table = render_table(
        ["Servicio", "Estado", "Autoarranque", "Python path", "Odoo home", "Config hint"],
        services_rows if services_rows else [["(sin servicios detectados)", "", "", "", "", ""]],
    )
    print(f"\n{title('Servicios Odoo detectados')}\n{services_table}")
    report_sections.append("Servicios Odoo detectados\n" + strip_ansi(services_table))

    artifacts_table = render_table(
        ["Tipo", "Cantidad", "Muestra"],
        [
            ["Dirs con 'odoo'", str(len(named_dirs)), ", ".join(named_dirs[:3]) or "-"],
            ["Configs Odoo", str(len(conf_paths)), ", ".join(conf_paths[:3]) or "-"],
            ["Configs Nginx relacionadas", str(len(nginx_paths)), ", ".join(nginx_paths[:3]) or "-"],
            ["Filestore roots", str(len(filestore_roots)), ", ".join(filestore_roots[:3]) or "-"],
        ],
    )
    print(f"\n{title('Artefactos detectados por búsqueda')}\n{artifacts_table}")
    report_sections.append("Artefactos detectados por búsqueda\n" + strip_ansi(artifacts_table))

    if conf_paths:
        conf_table = render_table(
            ["#", "Config Odoo"],
            [[str(idx), path] for idx, path in enumerate(conf_paths, start=1)],
        )
        print(f"\n{title('Archivos de configuración Odoo detectados')}\n{conf_table}")
        report_sections.append("Archivos de configuración Odoo detectados\n" + strip_ansi(conf_table))

    if nginx_paths:
        nginx_table = render_table(
            ["#", "Config Nginx"],
            [[str(idx), path] for idx, path in enumerate(nginx_paths, start=1)],
        )
        print(f"\n{title('Configs Nginx relacionadas con Odoo')}\n{nginx_table}")
        report_sections.append("Configs Nginx relacionadas con Odoo\n" + strip_ansi(nginx_table))

    if filestore_roots:
        filestore_rows: list[list[str]] = []
        for idx, root in enumerate(filestore_roots, start=1):
            db_count = 0
            try:
                db_count = len(
                    [
                        name
                        for name in os.listdir(root)
                        if os.path.isdir(os.path.join(root, name)) and not name.startswith(".")
                    ]
                )
            except OSError:
                db_count = 0
            filestore_rows.append([str(idx), root, str(db_count)])
        filestore_table = render_table(["#", "Filestore root", "DB dirs"], filestore_rows)
        print(f"\n{title('Filestores detectados')}\n{filestore_table}")
        report_sections.append("Filestores detectados\n" + strip_ansi(filestore_table))

    instance_rows = _collect_external_instance_rows(
        service_contexts=service_contexts,
        conf_paths=conf_paths,
        nginx_paths=nginx_paths,
        filestore_roots=filestore_roots,
    )
    odoo_rows: list[list[str]] = []
    python_rows: list[list[str]] = []
    nginx_rows: list[list[str]] = []
    for row in instance_rows:
        odoo_rows.append(
            [
                row[0],
                row[1],
                row[2],
                row[3],
                row[4],
                row[5],
                row[6],
                row[7],
                row[8],
                row[12],
                row[13],
                _cell_multiline(row[14]),
                _cell_multiline(row[24]),
            ]
        )
        python_rows.append(
            [
                row[0],
                row[10],
                row[25],
                row[26],
                _cell_multiline(row[15]),
            ]
        )
        nginx_rows.append(
            [
                row[0],
                _cell_multiline(row[16]),
                row[4],
                row[5],
                row[19],
                row[24],
                row[25],
            ]
        )

    odoo_table = render_table(
        [
            "Instancia",
            "Servicio",
            "Autoarranque",
            "Odoo",
            "HTTP",
            "gevent",
            "DB host",
            "DB user",
            "DB port",
            "Config Odoo",
            "Data dir",
            "Filestores",
            "DBs locales",
        ],
        odoo_rows if odoo_rows else [["(sin instancias detectadas)", "", "", "", "", "", "", "", "", "", "", "", ""]],
    )
    print(f"\n{title('Instancias: Odoo / rutas / DB')}\n{odoo_table}")
    report_sections.append("Instancias: Odoo / rutas / DB\n" + strip_ansi(odoo_table))

    python_table = render_table(
        ["Instancia", "Python", "Python path", "Workers", "Addons"],
        python_rows if python_rows else [["(sin instancias detectadas)", "", "", "", ""]],
    )
    print(f"\n{title('Instancias: Python')}\n{python_table}")
    report_sections.append("Instancias: Python\n" + strip_ansi(python_table))

    nginx_table_by_instance = render_table(
        ["Instancia", "server_name", "HTTP", "gevent", "TLS tipo", "Nginx cfgs", "Filestore roots"],
        nginx_rows if nginx_rows else [["(sin instancias detectadas)", "", "", "", "", "", ""]],
    )
    print(f"\n{title('Instancias: Nginx / puertos')}\n{nginx_table_by_instance}")
    report_sections.append("Instancias: Nginx / puertos\n" + strip_ansi(nginx_table_by_instance))

    cert_details_map: dict[str, dict[str, str | set[str]]] = {}
    for row in instance_rows:
        instance_name = row[0]
        server_names = [item.strip() for item in row[16].split(",") if item.strip()]
        cert_paths = [item.strip() for item in row[17].split(",") if item.strip()]
        key_paths = [item.strip() for item in row[18].split(",") if item.strip()]
        tls_type = row[19]
        issuer = row[20]
        subject = row[21]
        expires = row[22]
        serial = row[23]

        for cert_path in cert_paths:
            item = cert_details_map.setdefault(
                cert_path,
                {
                    "key": ", ".join(key_paths),
                    "type": tls_type,
                    "issuer": issuer,
                    "subject": subject,
                    "expires": expires,
                    "serial": serial,
                    "instances": set(),
                    "server_names": set(),
                },
            )
            instances = item["instances"]
            if isinstance(instances, set):
                instances.add(instance_name)
            names = item["server_names"]
            if isinstance(names, set):
                for name in server_names:
                    names.add(name)

    if cert_details_map:
        cert_rows: list[list[str]] = []
        for cert_path in sorted(cert_details_map):
            item = cert_details_map[cert_path]
            instances = item["instances"]
            server_names = item["server_names"]
            cert_rows.append(
                [
                    cert_path,
                    _cell_multiline(str(item["key"])),
                    str(item["type"]),
                    _cell_multiline(str(item["issuer"])),
                    _cell_multiline(str(item["subject"])),
                    str(item["expires"]),
                    ", ".join(sorted(instances)) if isinstance(instances, set) else "",
                    _cell_multiline(", ".join(sorted(server_names)) if isinstance(server_names, set) else ""),
                ]
            )

        cert_table = render_table(
            [
                "TLS cert",
                "TLS key",
                "Tipo",
                "Issuer",
                "Subject",
                "Expira",
                "Instancias",
                "server_name",
            ],
            cert_rows,
        )
        print(f"\n{title('Detalle de certificados TLS')}\n{cert_table}")
        report_sections.append("Detalle de certificados TLS\n" + strip_ansi(cert_table))

    run_active_checks = ask_bool(
        "¿Ejecutar comprobaciones activas de certificados TLS?",
        True,
    )
    if run_active_checks:
        threshold_days = ask_int(
            "Umbral de alerta para expiración TLS (días)",
            120,
        )
        cert_paths: set[str] = set(cert_details_map.keys())

        if cert_paths:
            check_rows: list[list[str]] = []
            for cert_path in sorted(cert_paths):
                status, detail = _certificate_expiry_status(cert_path, threshold_days)
                check_rows.append([level_tag(status), cert_path, detail])

            checks_table = render_table(["Estado", "Certificado", "Resultado"], check_rows)
            print(f"\n{title('Comprobaciones activas TLS')}\n{checks_table}")
            report_sections.append("Comprobaciones activas TLS\n" + strip_ansi(checks_table))
        else:
            info_message = level_text("INFO", "No hay rutas de certificados TLS detectadas para comprobación activa.")
            print(info_message)
            report_sections.append("Comprobaciones activas TLS\n" + strip_ansi(info_message))

    export_report = ask_bool("¿Quieres exportar el informe a archivo?", True)
    if not export_report:
        print(level_text("INFO", "Exportación omitida por el usuario."))
        return

    now = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    host = socket.gethostname()
    default_path = f"./reports/{host}_{now}.txt"
    export_path = ask_text("Ruta de exportación del informe", default_path, required=True)

    export_dir = os.path.dirname(export_path) or "."
    os.makedirs(export_dir, exist_ok=True)
    with open(export_path, "w", encoding="utf-8") as file_handle:
        file_handle.write("\n\n".join(report_sections) + "\n")

    print(level_text("OK", f"Informe exportado en: {export_path}"))
