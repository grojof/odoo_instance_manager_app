"""Manage an existing instance: status, config update, logs, venv, delete."""

from __future__ import annotations

import datetime

from ..i18n import t, tf
from ..models import InstanceConfig
from ..planners import (
    plan_nginx_http,
    plan_nginx_https,
    plan_odoo_base_setup,
    posture_rows,
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
    detect_cpu_count,
    detect_nginx_version,
    path_exists,
    read_odoo_conf,
    service_active,
    service_enabled,
    service_exists,
    user_exists,
    wkhtmltopdf_version,
)
from ..ui import level_tag, level_text, render_table, title
from .addons import show_addon_inventory
from .backup_restore import (
    _backup_instance,
    _duplicate_database,
    _duplicate_instance,
    _restore_backup,
)
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
from .scheduled_backup import manage_scheduled_backup


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
            return 'Self-signed', has_expected_files
        return "Personalizado (CA)", has_expected_files

    if cert_path and key_path:
        return "Personalizado (externo)", path_exists(cert_path) and path_exists(key_path)

    return 'Incomplete TLS configuration', False


def _show_locations_view(config: InstanceConfig) -> None:
    print(f"\n{title('Expected locations and names')}")
    path_rows = [[key, value] for key, value in pretty_paths(config)]
    print(render_table(['Field', 'Value'], path_rows))

    print(f"\n{title('Relevant instance locations')}")
    rows = [
        ["Odoo config", config.odoo_conf_file],
        ["Odoo home", config.odoo_home],
        ["Nginx HTTP", f"/etc/nginx/sites-available/{config.nginx_http_name}"],
        ["Nginx HTTPS", f"/etc/nginx/sites-available/{config.nginx_https_name}"],
        ["SSL dir", config.nginx_ssl_dir],
        ["Data store (data_dir)", _resolve_data_dir(config)],
    ]
    print(render_table(['Item', 'Path/Value'], rows))


def _show_detected_state_view(
    config: InstanceConfig,
    db_error: str | None = None,
    listed_dbs: list[str] | None = None,
) -> None:
    data_dir = _resolve_data_dir(config)

    print(f"\n{title('Detected state')}")
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
        status_rows.append(["MISSING", "DB listing", tf("connection/query failure -> {}", db_error)])
    elif listed_dbs is not None:
        status_rows.append(["OK", "DB listing", tf("{} DB(s) detected", len(listed_dbs))])

    if config.db_name:
        status_rows.append([
            "OK" if database_exists(config.db_name) else "MISSING",
            "DB database",
            config.db_name,
        ])
    else:
        status_rows.append(["INFO", "DB database", 'not provided, validation skipped'])

    labeled_rows = [[level_tag(state), label, value] for state, label, value in status_rows]
    print(render_table(['State', 'Check', 'Value'], labeled_rows))


def _show_config_values_view(config: InstanceConfig) -> None:
    conf_values = read_odoo_conf(config.odoo_conf_file)
    if not conf_values:
        print(level_text("INFO", tf('No readable Odoo config at {}.', config.odoo_conf_file)))
        return
    print(f"\n{title('Useful values in the Odoo config')}")
    conf_rows: list[list[str]] = []
    for key in [
        "db_host",
        "db_port",
        "db_user",
        "addons_path",
        "data_dir",
        "http_port",
        "gevent_port",
        "longpolling_port",
        "list_db",
        "dbfilter",
        "workers",
        "db_sslmode",
    ]:
        if key in conf_values:
            conf_rows.append([key, conf_values[key]])
    if conf_rows:
        print(render_table(['Key', 'Value'], conf_rows))


def _show_posture_view(config: InstanceConfig) -> None:
    conf_values = read_odoo_conf(config.odoo_conf_file)
    if not conf_values:
        print(level_text("INFO", tf('No readable Odoo config at {}.', config.odoo_conf_file)))
        return
    rows = posture_rows(
        instance=config.instance,
        conf_values=conf_values,
        wkhtmltopdf_ver=wkhtmltopdf_version(),
        cpu_count=detect_cpu_count(),
    )
    print(f"\n{title('Security & production posture')}")
    labeled = [[level_tag(state), check, detail] for state, check, detail in rows]
    print(render_table(['State', 'Check', 'Detail'], labeled))


def _repair_instance_nginx_logs(config: InstanceConfig) -> None:
    access_log = f"/var/log/nginx/{config.instance}.access.log"
    error_log = f"/var/log/nginx/{config.instance}.error.log"

    commands: list[Command] = [
        Command(
            'Ensure /var/log/nginx directory',
            "install -d -m 755 -o root -g adm /var/log/nginx",
        ),
        Command(
            'Recreate instance access log',
            f"install -m 640 -o www-data -g adm /dev/null {_quote(access_log)}",
        ),
        Command(
            'Recreate instance error log',
            f"install -m 640 -o www-data -g adm /dev/null {_quote(error_log)}",
        ),
        Command('Validate Nginx', "nginx -t"),
        Command(
            'Reopen Nginx logs',
            "nginx -s reopen || systemctl reload nginx",
        ),
        Command(
            'Show final log permissions',
            f"ls -l {_quote(access_log)} {_quote(error_log)}",
        ),
    ]

    _execute_plan(commands)


def _install_python_packages_in_instance_venv(config: InstanceConfig) -> None:
    venv_activate = f"{config.odoo_home}/venv/bin/activate"
    venv_pip = f"{config.odoo_home}/venv/bin/pip"

    print(f"\n{title('Install Python packages in the instance venv')}")
    print(level_text("INFO", tf('Target venv: {}/venv', config.odoo_home)))

    mode = choose(
        'Package source',
        [
            'requirements.txt (select path)',
            'Manual package list',
            'Cancel',
        ],
        default_index=None,
    )
    if mode in {"", 'Cancel'}:
        return

    commands: list[Command] = [
        Command(
            'Validate the instance venv',
            f"test -x {_quote(venv_pip)}",
        )
    ]

    if mode == 'requirements.txt (select path)':
        print(level_text("INFO", 'Select the requirements file to install.'))
        req_path = select_file_path(
            ".",
            "Archivo requirements (TXT/IN)",
            (".txt", ".in"),
        )
        commands.append(
            Command(
                'Validate requirements file',
                f"test -f {_quote(req_path)}",
            )
        )
        commands.append(
            Command(
                'Install packages from requirements into the venv',
                f"sudo -u {_quote(config.odoo_user)} bash -lc \"source {_quote(venv_activate)} && pip install -r {_quote(req_path)}\"",
            )
        )
    else:
        print(level_text("INFO", 'Manual format supported:'))
        print(level_text("INFO", '- Comma-separated on a single line'))
        print(level_text("INFO", '- Or one dependency per line (empty Enter to finish)'))
        print(level_text("INFO", "- requests"))
        print(level_text("INFO", "- psycopg2-binary==2.9.10"))
        print(level_text("INFO", "- babel>=2.14,<3"))

        raw_packages = ask_text(
            'Initial package list (comma-separated or one line)',
            "",
            required=False,
        )

        extra_lines: list[str] = []
        print(level_text("INFO", 'Add more packages (one per line). Empty Enter to finish.'))
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
            print(level_text("WARN", 'No valid packages detected. Operation cancelled.'))
            return

        package_args = " ".join(_quote(package) for package in packages)
        commands.append(
            Command(
                'Install packages into the venv',
                f"sudo -u {_quote(config.odoo_user)} bash -lc \"source {_quote(venv_activate)} && pip install {package_args}\"",
            )
        )

    commands.append(
        Command(
            'Show installed packages (summary)',
            f"sudo -u {_quote(config.odoo_user)} bash -lc \"source {_quote(venv_activate)} && pip list\"",
        )
    )

    _execute_plan(commands)


def _load_config_from_conf(config: InstanceConfig, values: dict[str, str]) -> None:
    """Populate a config from an existing ``odoo.conf`` so a regeneration preserves
    the instance's current credentials and production-posture settings instead of
    silently resetting them."""
    if not values:
        return

    def _int(key: str, current: int) -> int:
        raw = values.get(key, "").strip()
        return int(raw) if raw.isdigit() else current

    config.db_host = values.get("db_host", config.db_host)
    config.db_port = _int("db_port", config.db_port)
    config.db_user = values.get("db_user", config.db_user)
    config.db_password = values.get("db_password", config.db_password)
    config.odoo_admin_passwd = values.get("admin_passwd", config.odoo_admin_passwd)
    config.http_port = _int("http_port", config.http_port)

    # Preserve the live-chat/bus port under whichever key the instance already uses;
    # a lone longpolling_port implies an Odoo ≤ 15 instance.
    if values.get("gevent_port", "").strip().isdigit():
        config.gevent_port = int(values["gevent_port"])
    elif values.get("longpolling_port", "").strip().isdigit():
        config.gevent_port = int(values["longpolling_port"])
        config.version = "15"

    if "list_db" in values:
        config.list_db = values.get("list_db", "").strip().lower() in {"true", "1", "yes"}
    config.dbfilter = values.get("dbfilter", config.dbfilter)
    config.db_sslmode = values.get("db_sslmode", config.db_sslmode)
    for key in (
        "workers",
        "max_cron_threads",
        "limit_memory_soft",
        "limit_memory_hard",
        "limit_request",
        "limit_time_cpu",
        "limit_time_real",
    ):
        setattr(config, key, _int(key, getattr(config, key)))


def update_existing_configs(instance: str) -> None:
    config = InstanceConfig(instance=instance)
    _load_config_from_conf(config, read_odoo_conf(config.odoo_conf_file))
    config.normalize_defaults()

    print(t('\nEnter new values (if applicable)'))
    config.domain = ask_text('Domain', config.domain, required=True)
    config.http_port = ask_int('Internal HTTP', config.http_port)
    config.gevent_port = ask_int('Internal gevent', config.gevent_port)
    config.db_host = ask_text('DB host', config.db_host, required=True)
    config.db_port = ask_int('DB port', config.db_port)
    config.db_user = ask_text('DB user', config.db_user, required=True)
    config.db_password = ask_text('DB password', config.db_password, required=True)
    config.odoo_admin_passwd = ask_text(
        'Odoo admin_passwd', config.odoo_admin_passwd, required=True
    )
    config.ensure_strong_secrets()

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
    print(f"\n{title('Pre-update configuration backup')}")
    print(render_table(['Item', "Origen", "Destino backup"], backup_rows))

    backup_commands: list[Command] = [
        Command(
            'Create configuration backup directory',
            f"mkdir -p {_quote(backup_dest)}",
        )
    ]
    for name, source in backup_sources:
        target_name = name.replace(" ", "_")
        backup_commands.append(
            Command(
                tf('Pre-update backup of {}', name),
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

    nginx_version = detect_nginx_version()
    nginx_mode = choose(
        'Regenerate Nginx',
        ["No", 'Yes - HTTP', 'Yes - HTTPS'],
        default_index=None,
    )
    if nginx_mode == 'Yes - HTTP':
        commands.extend(plan_nginx_http(config, nginx_version))
    elif nginx_mode == 'Yes - HTTPS':
        commands.extend(_maybe_plan_certs(config))
        commands.extend(plan_nginx_https(config, nginx_version))

    _execute_plan(commands)
    print(level_text("INFO", tf('Configuration backup (if the plan ran) at: {}', backup_dest)))


def _delete_instance(
    config: InstanceConfig, cached: DbCredentials | None = None
) -> DbCredentials | None:
    drop_db = ask_bool('Also delete the database?', False)
    remove_store = ask_bool('Also delete the filestore?', False)

    db_name = ""
    db_host = ""
    db_port = 5432
    db_user = ""
    db_password = ""
    creds = cached

    if drop_db:
        db_name = ask_text('DB to delete', config.instance, required=True)
        creds = _ask_db_credentials(config.instance, cached)
        db_host, db_port, db_user, db_password = creds.host, creds.port, creds.user, creds.password
        if not _database_exists(creds, db_name):
            print(
                level_text(
                    "WARN",
                    tf("Database '{}' not found on {}:{} (missing or unreachable); skipping its deletion.", db_name, creds.host, creds.port),
                )
            )
            drop_db = False

    commands: list[Command] = [
        Command(
            'Stop the Odoo service',
            f"systemctl stop {_quote(config.odoo_service)} || true",
        ),
        Command(
            'Disable the Odoo service',
            f"systemctl disable {_quote(config.odoo_service)} || true",
        ),
        Command(
            'Remove unit file',
            f"rm -f {_quote(f'/etc/systemd/system/{config.odoo_service}.service')}",
        ),
        Command('Reload systemd', "systemctl daemon-reload"),
        Command(
            'Remove Odoo configuration', f"rm -rf {_quote(config.odoo_conf_dir)}"
        ),
        Command('Remove instance home', f"rm -rf {_quote(config.odoo_home)}"),
        Command(
            'Remove Nginx HTTP',
            f"rm -f {_quote(f'/etc/nginx/sites-available/{config.nginx_http_name}')} {_quote(f'/etc/nginx/sites-enabled/{config.nginx_http_name}')}",
        ),
        Command(
            'Remove Nginx HTTPS',
            f"rm -f {_quote(f'/etc/nginx/sites-available/{config.nginx_https_name}')} {_quote(f'/etc/nginx/sites-enabled/{config.nginx_https_name}')}",
        ),
        Command('Remove instance SSL', f"rm -rf {_quote(config.nginx_ssl_dir)}"),
        Command('Validate Nginx', "nginx -t"),
        Command('Reload Nginx', "systemctl reload nginx || true"),
    ]

    if drop_db and db_name:
        commands.append(
            Command(
                'Delete DB',
                f"PGPASSWORD={_quote(db_password)} dropdb --if-exists -h {_quote(db_host)} -p {db_port} -U {_quote(db_user)} {_quote(db_name)}",
            )
        )

    if remove_store:
        store_db = ask_text(
            'Filestore DB to delete', db_name or config.instance, required=True
        )
        if not _is_safe_path_component(store_db):
            print(
                level_text(
                    "ERROR",
                    "Invalid filestore DB name ('/', '..' and reserved names are not allowed).",
                )
            )
            return creds
        commands.append(
            Command(
                'Remove filestore',
                f"rm -rf {_quote(_filestore_path(config, store_db))}",
            )
        )

    if not confirm_with_phrase(
        'Destructive action detected.',
        f"DELETE {config.instance}",
    ):
        print(level_text("INFO", 'Invalid confirmation. Operation cancelled.'))
        return creds

    _execute_plan(commands)
    return creds


def manage_existing_instance() -> None:
    instance = _select_existing_instance()
    if not instance:
        print(t('[INFO] Operation cancelled.'))
        return

    config = _validate_instance_or_abort(instance)
    if config is None:
        return

    config.db_name, db_error, listed_dbs = _probe_databases_for_management(instance)
    db_creds: DbCredentials | None = None

    while True:
        action = choose(
            tf('\nSafe instance management: {}', instance),
            [
                'Status: locations & names',
                'Status: detected resources',
                'Status: config values',
                'Status: security & production',
                'Health check',
                'Update existing configuration',
                'Repair instance Nginx logs',
                'Log rotation',
                'Disk usage and cleanup',
                'Install Python packages in the venv',
                'Addon inventory',
                'Create backup',
                'Scheduled backups',
                'Restore backup',
                'Duplicate database',
                'Duplicate instance',
                'Delete instance',
                'Back',
            ],
            default_index=None,
        )

        if action in {"", 'Back'}:
            return

        if action == 'Status: locations & names':
            _show_locations_view(config)
        elif action == 'Status: detected resources':
            _show_detected_state_view(config, db_error=db_error, listed_dbs=listed_dbs)
        elif action == 'Status: config values':
            _show_config_values_view(config)
        elif action == 'Status: security & production':
            _show_posture_view(config)
        elif action == 'Health check':
            run_health_check(config)
        elif action == 'Update existing configuration':
            update_existing_configs(instance)
            config = InstanceConfig(instance=instance)
            config.db_name, db_error, listed_dbs = _probe_databases_for_management(
                instance
            )
            config.normalize_defaults()
        elif action == 'Repair instance Nginx logs':
            _repair_instance_nginx_logs(config)
        elif action == 'Log rotation':
            manage_log_rotation(config)
        elif action == 'Disk usage and cleanup':
            manage_disk_usage(config)
        elif action == 'Install Python packages in the venv':
            _install_python_packages_in_instance_venv(config)
        elif action == 'Addon inventory':
            show_addon_inventory(config)
        elif action == 'Create backup':
            db_creds = _backup_instance(config, db_creds)
        elif action == 'Scheduled backups':
            manage_scheduled_backup(config)
        elif action == 'Restore backup':
            db_creds = _restore_backup(config, db_creds)
        elif action == 'Duplicate database':
            db_creds = _duplicate_database(config, db_creds)
        elif action == 'Duplicate instance':
            db_creds = _duplicate_instance(config, db_creds)
        elif action == 'Delete instance':
            db_creds = _delete_instance(config, db_creds)
