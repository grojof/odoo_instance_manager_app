"""Manage an existing instance: status, config update, logs, venv, delete."""

from __future__ import annotations

import datetime

from ..models import InstanceConfig
from ..planners import (
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
    database_exists,
    db_role_exists,
    path_exists,
    read_odoo_conf,
    service_active,
    service_enabled,
    service_exists,
    user_exists,
)
from ..ui import level_tag, level_text, render_table, title
from .addons import show_addon_inventory
from .backup_restore import _backup_instance, _duplicate_instance, _restore_backup
from .common import (
    DbCredentials,
    _ask_db_credentials,
    _database_exists,
    _execute_plan,
    _filestore_path,
    _is_safe_path_component,
    _is_self_signed_certificate,
    _probe_databases_for_management,
    _quote,
    _resolve_data_dir,
    _select_existing_instance,
    _validate_instance_or_abort,
)
from .diskusage import manage_disk_usage
from .health import run_health_check
from .install import _maybe_plan_certs
from .logrotate import manage_log_rotation


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


def _delete_instance(
    config: InstanceConfig, cached: DbCredentials | None = None
) -> DbCredentials | None:
    drop_db = ask_bool("¿Eliminar también base de datos?", False)
    remove_store = ask_bool("¿Eliminar también filestore?", False)

    db_name = ""
    db_host = ""
    db_port = 5432
    db_user = ""
    db_password = ""
    creds = cached

    if drop_db:
        db_name = ask_text("DB a eliminar", config.instance, required=True)
        creds = _ask_db_credentials(config.instance, cached)
        db_host, db_port, db_user, db_password = creds.host, creds.port, creds.user, creds.password
        if not _database_exists(creds, db_name):
            print(
                level_text(
                    "WARN",
                    f"No se encontró la base de datos '{db_name}' en {creds.host}:{creds.port} "
                    "(no existe o no se pudo conectar); se omite su eliminación.",
                )
            )
            drop_db = False

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
                f"PGPASSWORD={_quote(db_password)} dropdb --if-exists -h {_quote(db_host)} -p {db_port} -U {_quote(db_user)} {_quote(db_name)}",
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
            return creds
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
        print(level_text("INFO", "Confirmación no válida. Operación cancelada."))
        return creds

    _execute_plan(commands)
    return creds


def manage_existing_instance() -> None:
    instance = _select_existing_instance()
    if not instance:
        print("[INFO] Operación cancelada.")
        return

    config = _validate_instance_or_abort(instance)
    if config is None:
        return

    config.db_name, db_error, listed_dbs = _probe_databases_for_management(instance)
    db_creds: DbCredentials | None = None

    while True:
        print("\nEstado completo de la instancia:")
        _show_instance_status(config, db_error=db_error, listed_dbs=listed_dbs)

        action = choose(
            f"\nGestión segura de instancia: {instance}",
            [
                "Consultar ubicaciones/config actual",
                "Comprobar salud (health check)",
                "Actualizar configuración existente",
                "Reparar logs Nginx de instancia",
                "Rotación de logs",
                "Uso de disco y limpieza",
                "Instalar paquetes Python en venv",
                "Inventario de addons",
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
        elif action == "Comprobar salud (health check)":
            run_health_check(config)
        elif action == "Actualizar configuración existente":
            update_existing_configs(instance)
            config = InstanceConfig(instance=instance)
            config.db_name, db_error, listed_dbs = _probe_databases_for_management(
                instance
            )
            config.normalize_defaults()
        elif action == "Reparar logs Nginx de instancia":
            _repair_instance_nginx_logs(config)
        elif action == "Rotación de logs":
            manage_log_rotation(config)
        elif action == "Uso de disco y limpieza":
            manage_disk_usage(config)
        elif action == "Instalar paquetes Python en venv":
            _install_python_packages_in_instance_venv(config)
        elif action == "Inventario de addons":
            show_addon_inventory(config)
        elif action == "Realizar backup":
            db_creds = _backup_instance(config, db_creds)
        elif action == "Restaurar backup":
            db_creds = _restore_backup(config, db_creds)
        elif action == "Duplicar instancia":
            db_creds = _duplicate_instance(config, db_creds)
        elif action == "Eliminar instancia":
            db_creds = _delete_instance(config, db_creds)
