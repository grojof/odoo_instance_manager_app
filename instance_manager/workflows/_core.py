from __future__ import annotations

import datetime
import os
import re
import shlex
import uuid

from ..models import InstanceConfig
from ..planners import (
    _sql_literal,
    plan_copy_custom_certs,
    plan_db_setup,
    plan_ensure_db_role,
    plan_ensure_self_signed_certs,
    plan_nginx_http,
    plan_nginx_https,
    plan_odoo_base_setup,
    pretty_paths,
)
from ..prompts import (
    ask_bool,
    ask_int,
    ask_text,
    choose,
    confirm_with_phrase,
    select_file_path,
)
from ..system import (
    Command,
    apply_commands,
    database_exists,
    db_role_exists,
    list_instances,
    path_exists,
    read_odoo_conf,
    run,
    service_active,
    service_enabled,
    service_exists,
    user_exists,
)
from ..ui import level_tag, level_text, render_table, title
from .common import (
    _execute_plan,
    _filestore_path,
    _is_safe_path_component,
    _is_self_signed_certificate,
    _odoo_conf_candidates,
    _probe_databases_for_management,
    _quote,
    _resolve_data_dir,
    _select_db_name,
    _select_existing_instance,
    _validate_instance_or_abort,
)


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

