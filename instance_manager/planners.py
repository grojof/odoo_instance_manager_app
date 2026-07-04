from __future__ import annotations

import re
import shlex

from .i18n import tf
from .models import InstanceConfig
from .system import Command


def _sql_literal(value: str) -> str:
    return value.replace("'", "''")


def _is_local_db_host(db_host: str) -> bool:
    value = (db_host or "").strip().lower()
    return value in {
        "",
        "false",
        "none",
        "localhost",
        "127.0.0.1",
        "::1",
        "/var/run/postgresql",
    }


def _db_role_create_if_missing_sql(config: InstanceConfig) -> str:
    db_user_literal = _sql_literal(config.db_user)
    db_password_literal = _sql_literal(config.db_password)
    return (
        "DO $$ "
        "BEGIN "
        f"IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='{db_user_literal}') THEN "
        f"CREATE ROLE {config.db_user} WITH LOGIN CREATEDB PASSWORD '{db_password_literal}'; "
        "ELSE "
        f"ALTER ROLE {config.db_user} WITH LOGIN CREATEDB; "
        f"RAISE NOTICE 'Role {db_user_literal} already exists; reusing it without changing the password.'; "
        "END IF; "
        "END "
        "$$;"
    )


def _db_connectivity_check_command(config: InstanceConfig) -> str:
    check_host = config.db_host
    if _is_local_db_host(check_host):
        check_host = "127.0.0.1"
    return (
        f"PGPASSWORD={shlex.quote(config.db_password)} "
        f"psql -h {shlex.quote(check_host)} -p {config.db_port} -U {shlex.quote(config.db_user)} "
        "-d postgres -tAc \"SELECT 1;\" >/dev/null"
    )


def _odoo_conf_content(config: InstanceConfig) -> str:
    """Render the instance ``odoo.conf``.

    Version-adaptive: the live-chat/bus port key is ``gevent_port`` on Odoo ≥ 16
    and ``longpolling_port`` on ≤ 15. Production posture (``list_db``, ``dbfilter``,
    derived ``workers``/memory limits) and ``db_sslmode`` for a remote DB host are
    written from the resolved config. Pure — all values are passed in.
    """
    lines = [
        "[options]",
        f"admin_passwd = {config.odoo_admin_passwd}",
        f"list_db = {config.list_db}",
        "",
        f"addons_path = {config.odoo_home}/odoo/addons,"
        f"{config.odoo_home}/addons-oca,{config.odoo_home}/addons-custom",
        "",
        "http_interface = 127.0.0.1",
        f"http_port = {config.http_port}",
        f"{config.gevent_port_key} = {config.gevent_port}",
        "proxy_mode = True",
        "",
        f"logfile = {config.odoo_log_file}",
        "",
        f"workers = {config.workers}",
        f"max_cron_threads = {config.max_cron_threads}",
        f"limit_memory_soft = {config.limit_memory_soft}",
        f"limit_memory_hard = {config.limit_memory_hard}",
        f"limit_request = {config.limit_request}",
        f"limit_time_cpu = {config.limit_time_cpu}",
        f"limit_time_real = {config.limit_time_real}",
        "",
        f"db_host = {config.db_host}",
        f"db_port = {config.db_port}",
        f"db_user = {config.db_user}",
        f"db_password = {config.db_password}",
    ]
    # A blank dbfilter means "no filtering" — omit the key entirely (Odoo then
    # serves all databases). Only write it when the operator set one.
    if config.dbfilter:
        lines.insert(3, f"dbfilter = {config.dbfilter}")
    if config.is_remote_db_host and config.db_sslmode:
        lines.append(f"db_sslmode = {config.db_sslmode}")
    return "\n".join(lines) + "\n"


_GIB = 1024**3


def compute_worker_tuning(cpu_count: int, ram_bytes: int | None) -> dict[str, int]:
    """Pure worker/memory sizing from detected resources.

    ``workers = (cpu * 2) + 1`` (Odoo's guidance), then capped so the worker + cron
    steady-state memory budget (~1 GiB/process) fits detected RAM after an
    OS/PostgreSQL reserve. A floor of 2 keeps a production host multi-process; the
    per-worker soft/hard limits are ceilings, not steady use. Operators override.
    """
    cpu = max(1, cpu_count)
    max_cron_threads = 2 if cpu >= 4 else 1
    workers = (cpu * 2) + 1
    if ram_bytes and ram_bytes > 0:
        reserve = max(_GIB, int(ram_bytes * 0.2))
        available = max(0, ram_bytes - reserve)
        per_process = _GIB
        max_by_ram = available // per_process - max_cron_threads
        workers = max(2, min(workers, int(max_by_ram)))
    return {
        "workers": workers,
        "max_cron_threads": max_cron_threads,
        "limit_memory_soft": 2147483648,
        "limit_memory_hard": 2684354560,
        "limit_request": 8192,
    }


def _systemd_content(config: InstanceConfig) -> str:
    return f"""[Unit]
Description=Odoo {config.version} ({config.instance})
After=network.target

[Service]
Type=simple
User={config.odoo_user}
Group={config.odoo_user}
WorkingDirectory={config.odoo_home}/odoo
ExecStart={config.odoo_home}/venv/bin/python3 {config.odoo_home}/odoo/odoo-bin -c {config.odoo_conf_file}
Restart=always
RestartSec=3
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
"""


def _https_listen_block(nginx_version: tuple[int, int, int] | None) -> str:
    """The `listen`/http2 lines for the TLS server block, adapted to nginx.

    nginx ≥ 1.25.1 uses `listen … ssl;` plus a separate `http2 on;` (the `http2`
    listen parameter is deprecated there); older nginx uses `listen … ssl http2;`
    (the `http2 on;` directive does not exist and would fail `nginx -t`).
    """
    if nginx_version is not None and nginx_version >= (1, 25, 1):
        return "  listen 443 ssl;\n  http2 on;"
    return "  listen 443 ssl http2;"


def _nginx_http_content(config: InstanceConfig) -> str:
    return f"""upstream odoo_{config.instance} {{
  server 127.0.0.1:{config.http_port};
}}

upstream odoochat_{config.instance} {{
  server 127.0.0.1:{config.gevent_port};
}}

map $http_upgrade $connection_upgrade {{
  default upgrade;
  ''      close;
}}

server {{
  listen 80;
  server_name {config.domain};

  proxy_read_timeout 3600s;
  proxy_connect_timeout 720s;
  proxy_send_timeout 3600s;

  access_log /var/log/nginx/{config.instance}.access.log;
  error_log  /var/log/nginx/{config.instance}.error.log;

  location {config.live_chat_location} {{
    proxy_pass http://odoochat_{config.instance};
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;
    proxy_set_header X-Forwarded-Host $http_host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Real-IP $remote_addr;
  }}

  location / {{
    proxy_set_header X-Forwarded-Host $http_host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_redirect off;
    proxy_pass http://odoo_{config.instance};
  }}
}}
"""


def _nginx_https_content(
    config: InstanceConfig, nginx_version: tuple[int, int, int] | None = None
) -> str:
    listen_block = _https_listen_block(nginx_version)
    return f"""upstream odoo_{config.instance} {{
  server 127.0.0.1:{config.http_port};
}}

upstream odoochat_{config.instance} {{
  server 127.0.0.1:{config.gevent_port};
}}

map $http_upgrade $connection_upgrade {{
  default upgrade;
  ''      close;
}}

server {{
  listen 80;
  server_name {config.domain};
  rewrite ^(.*) https://$host$1 permanent;
}}

server {{
{listen_block}
  server_name {config.domain};

  client_max_body_size 2048m;

  ssl_certificate     {config.ssl_fullchain_file};
  ssl_certificate_key {config.ssl_key_file};
  ssl_protocols TLSv1.2 TLSv1.3;
  ssl_prefer_server_ciphers on;

  proxy_read_timeout 3600s;
  proxy_connect_timeout 720s;
  proxy_send_timeout 3600s;

  access_log /var/log/nginx/{config.instance}.access.log;
  error_log  /var/log/nginx/{config.instance}.error.log;

  location {config.live_chat_location} {{
    proxy_pass http://odoochat_{config.instance};
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;
    proxy_set_header X-Forwarded-Host $http_host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Real-IP $remote_addr;
  }}

  location / {{
    proxy_set_header X-Forwarded-Host $http_host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_redirect off;
    proxy_pass http://odoo_{config.instance};
  }}
}}
"""


def write_text_file_command(
    target_path: str, content: str, mode: str = "640"
) -> list[Command]:
    return [
        Command(
            description=tf("Write {}", target_path),
            command=f"cat > '{target_path}' <<'EOF'\n{content}\nEOF",
        ),
        Command(
            description=tf('Permissions {} on {}', mode, target_path),
            command=f"chmod {mode} '{target_path}'",
        ),
    ]


def _logrotate_content(
    config: InstanceConfig,
    frequency: str,
    rotate_count: int,
    compress: bool,
    maxsize: str,
) -> str:
    lines = [
        f"{config.odoo_log_file} {{",
        f"    {frequency}",
        f"    rotate {rotate_count}",
        "    missingok",
        "    notifempty",
        "    copytruncate",
        f"    su {config.odoo_user} {config.odoo_user}",
    ]
    if compress:
        lines.append("    compress")
        lines.append("    delaycompress")
    if maxsize:
        lines.append(f"    maxsize {maxsize}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def _nginx_logrotate_content(
    config: InstanceConfig,
    frequency: str,
    rotate_count: int,
    compress: bool,
) -> str:
    """Idiomatic Nginx stanza: `create` + `postrotate` reopen (Nginx reopens its
    logs on SIGUSR1), matching the distribution's own `nginx` logrotate — not
    `copytruncate`, which would risk losing lines Nginx *can* avoid losing."""
    lines = [
        f"{config.nginx_access_log} {config.nginx_error_log} {{",
        f"    {frequency}",
        f"    rotate {rotate_count}",
        "    missingok",
        "    notifempty",
        "    create 0640 www-data adm",
        "    sharedscripts",
    ]
    if compress:
        lines.append("    compress")
        lines.append("    delaycompress")
    lines.append("    postrotate")
    lines.append('        [ -f /run/nginx.pid ] && kill -USR1 "$(cat /run/nginx.pid)"')
    lines.append("    endscript")
    lines.append("}")
    return "\n".join(lines) + "\n"


def plan_logrotate_config(
    config: InstanceConfig,
    *,
    frequency: str = "weekly",
    rotate_count: int = 14,
    compress: bool = True,
    maxsize: str = "",
    remove_obsolete_odoo_key: bool = False,
    include_nginx: bool = False,
) -> list[Command]:
    """Build a system-logrotate policy for the instance's logs.

    The Odoo log uses ``copytruncate`` (Odoo does not reopen its log on a signal);
    the Nginx logs, when included, use ``create`` + a ``postrotate`` SIGUSR1 reopen
    (the modern Nginx-idiomatic method). Optionally strips a stale ``logrotate``
    key from the ``odoo.conf`` (Odoo's built-in log rotation was removed in Odoo 13,
    so the key is an ignored no-op that is cleaner to delete).
    """
    content = _logrotate_content(config, frequency, rotate_count, compress, maxsize)
    if include_nginx:
        content += "\n" + _nginx_logrotate_content(config, frequency, rotate_count, compress)

    commands: list[Command] = [
        Command(
            'Ensure logrotate is installed',
            "command -v logrotate >/dev/null 2>&1 || (apt-get update && apt-get -y install logrotate)",
        ),
    ]
    commands.extend(
        write_text_file_command(config.logrotate_config_file, content, "644")
    )
    commands.append(
        Command(
            'Validate logrotate configuration (dry-run)',
            f"logrotate -d {shlex.quote(config.logrotate_config_file)}",
        )
    )
    if remove_obsolete_odoo_key:
        commands.append(
            Command(
                "Remove obsolete 'logrotate' key from odoo.conf (Odoo ≥13 ignores it)",
                f"test -f {shlex.quote(config.odoo_conf_file)} && "
                f"sed -ri '/^[[:space:]]*logrotate[[:space:]]*=/d' "
                f"{shlex.quote(config.odoo_conf_file)} || true",
            )
        )
    return commands


def _safe_token(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", (value or "").strip())


def _fail2ban_base_content(
    ignore_ips: str,
    bantime: str,
    findtime: str,
    maxretry: int,
    recidive_bantime: str,
) -> str:
    return f"""[DEFAULT]
banaction = ufw
backend = auto
ignoreip = {ignore_ips}
bantime = {bantime}
findtime = {findtime}
maxretry = {maxretry}

[sshd]
enabled = true

[nginx-http-auth]
enabled = true

[nginx-botsearch]
enabled = true

[recidive]
enabled = true
logpath = /var/log/fail2ban.log
bantime = {recidive_bantime}
findtime = 1d
maxretry = 5
"""


def _fail2ban_odoo_filter_content() -> str:
    return r"""[INCLUDES]
before = common.conf

[Definition]
failregex = ^.*(?:login|authentication)\s+failed.*from\s+<HOST>.*$
            ^.*Login\s+failed\s+for\s+db:.*from\s+<HOST>.*$

ignoreregex =
"""


def _fail2ban_odoo_jail_content(
    jail_name: str,
    log_path: str,
    bantime: str,
    findtime: str,
    maxretry: int,
) -> str:
    return f"""[{jail_name}]
enabled = true
filter = odoo-auth
logpath = {log_path}
backend = auto
port = http,https
bantime = {bantime}
findtime = {findtime}
maxretry = {maxretry}
"""


def plan_fail2ban_base_setup(
    ignore_ips: str,
    bantime: str = "1h",
    findtime: str = "10m",
    maxretry: int = 8,
    recidive_bantime: str = "24h",
) -> list[Command]:
    jail_base_path = "/etc/fail2ban/jail.d/odoo-instance-manager.local"
    commands: list[Command] = [
        Command('Update packages', "apt-get update"),
        Command('Install fail2ban', "apt-get -y install fail2ban"),
        Command('Create /etc/fail2ban/jail.d', "mkdir -p /etc/fail2ban/jail.d"),
    ]
    commands.extend(
        write_text_file_command(
            jail_base_path,
            _fail2ban_base_content(
                ignore_ips=ignore_ips,
                bantime=bantime,
                findtime=findtime,
                maxretry=maxretry,
                recidive_bantime=recidive_bantime,
            ),
            "644",
        )
    )
    commands.extend(
        [
            Command('Validate fail2ban configuration', "fail2ban-client -t"),
            Command('Enable and start fail2ban', "systemctl enable --now fail2ban"),
            Command('Restart fail2ban', "systemctl restart fail2ban"),
            Command(
                'Wait for the fail2ban socket to be ready',
                "for i in $(seq 1 15); do fail2ban-client ping >/dev/null 2>&1 && exit 0; sleep 1; done; echo '[ERROR] fail2ban is active but its socket is unavailable after waiting.'; systemctl status fail2ban --no-pager -n 50 || true; exit 1",
            ),
        ]
    )
    return commands


def plan_fail2ban_enable_odoo_instance(
    instance: str,
    log_path: str,
    bantime: str = "1h",
    findtime: str = "10m",
    maxretry: int = 8,
) -> list[Command]:
    instance_token = _safe_token(instance)
    jail_name = f"odoo-auth-{instance_token}"
    filter_path = "/etc/fail2ban/filter.d/odoo-auth.conf"
    jail_path = f"/etc/fail2ban/jail.d/{jail_name}.local"

    commands: list[Command] = [
        Command('Ensure fail2ban is installed', "apt-get update && apt-get -y install fail2ban"),
        Command('Create fail2ban directories', "mkdir -p /etc/fail2ban/filter.d /etc/fail2ban/jail.d"),
    ]
    commands.extend(
        write_text_file_command(
            filter_path,
            _fail2ban_odoo_filter_content(),
            "644",
        )
    )
    commands.extend(
        write_text_file_command(
            jail_path,
            _fail2ban_odoo_jail_content(
                jail_name=jail_name,
                log_path=log_path,
                bantime=bantime,
                findtime=findtime,
                maxretry=maxretry,
            ),
            "644",
        )
    )
    commands.extend(
        [
            Command('Validate instance log', f"test -f {shlex.quote(log_path)}"),
            Command(
                'Test fail2ban regex against the Odoo log',
                f"fail2ban-regex {shlex.quote(log_path)} {shlex.quote(filter_path)}",
            ),
            Command('Validate fail2ban configuration', "fail2ban-client -t"),
            Command('Enable and start fail2ban', "systemctl enable --now fail2ban"),
            Command('Restart fail2ban', "systemctl restart fail2ban"),
            Command(
                'Wait for the fail2ban socket to be ready',
                "for i in $(seq 1 15); do fail2ban-client ping >/dev/null 2>&1 && exit 0; sleep 1; done; echo '[ERROR] fail2ban is active but its socket is unavailable after waiting.'; systemctl status fail2ban --no-pager -n 50 || true; exit 1",
            ),
        ]
    )
    return commands


def plan_fail2ban_ensure_odoo_filter() -> list[Command]:
    filter_path = "/etc/fail2ban/filter.d/odoo-auth.conf"

    commands: list[Command] = [
        Command('Create fail2ban filters directory', "mkdir -p /etc/fail2ban/filter.d"),
    ]
    commands.extend(
        write_text_file_command(
            filter_path,
            _fail2ban_odoo_filter_content(),
            "644",
        )
    )
    return commands


def plan_odoo_base_setup(config: InstanceConfig, service_autostart: bool = True) -> list[Command]:
    config.normalize_defaults()
    config.ensure_strong_secrets()
    config.validate_identifiers()
    commands: list[Command] = [
        Command('Update packages', "apt-get update"),
        Command(
            'Install Odoo base dependencies',
            "apt-get -y install git build-essential pkg-config python3 python3-venv python3-dev python3-pip "
            "libpq-dev libldap2-dev libsasl2-dev libssl-dev libffi-dev libxml2-dev libxslt1-dev "
            "libjpeg-dev zlib1g-dev libtiff-dev libopenjp2-7-dev liblcms2-dev libwebp-dev "
            "libharfbuzz-dev libfribidi-dev fontconfig postgresql-client xfonts-75dpi xfonts-base",
        ),
        Command(
            'Create system user (if missing)',
            f"id -u '{config.odoo_user}' >/dev/null 2>&1 || adduser --system --home '{config.odoo_home}' --group '{config.odoo_user}'",
        ),
        Command(
            'Create instance directories',
            f"mkdir -p '{config.odoo_home}/odoo' '{config.odoo_home}/addons-oca' '{config.odoo_home}/addons-custom' '{config.odoo_conf_dir}' /var/log/odoo",
        ),
        Command(
            'Adjust base ownership',
            f"chown -R '{config.odoo_user}:{config.odoo_user}' '{config.odoo_home}' /var/log/odoo",
        ),
        Command('Permissions on config folder', f"chmod 750 '{config.odoo_conf_dir}'"),
        Command(
            'Clone Odoo repo if missing',
            f"sudo -u '{config.odoo_user}' bash -lc \"test -d '{config.odoo_home}/odoo/.git' || git clone --depth 1 --branch '{config.repo_branch}' https://github.com/odoo/odoo.git '{config.odoo_home}/odoo'\"",
        ),
        Command(
            'Create/update venv and install requirements',
            f"sudo -u '{config.odoo_user}' bash -lc \"python3 -m venv '{config.odoo_home}/venv' && source '{config.odoo_home}/venv/bin/activate' && pip install --upgrade pip wheel setuptools && pip install -r '{config.odoo_home}/odoo/requirements.txt'\"",
        ),
    ]

    commands.extend(
        write_text_file_command(
            config.odoo_conf_file, _odoo_conf_content(config), "640"
        )
    )
    commands.extend(
        [
            Command(
                "Owner config dir",
                f"chown root:'{config.odoo_user}' '{config.odoo_conf_dir}'",
            ),
            Command(
                "Owner config Odoo",
                f"chown root:'{config.odoo_user}' '{config.odoo_conf_file}'",
            ),
        ]
    )

    service_path = f"/etc/systemd/system/{config.odoo_service}.service"
    commands.extend(
        write_text_file_command(service_path, _systemd_content(config), "644")
    )
    commands.append(Command('Reload systemd', "systemctl daemon-reload"))
    if service_autostart:
        commands.append(
            Command(
                'Enable and start the Odoo service',
                f"systemctl enable --now '{config.odoo_service}'",
            )
        )
    else:
        commands.extend(
            [
                Command(
                    'Disable Odoo service autostart',
                    f"systemctl disable '{config.odoo_service}' || true",
                ),
                Command(
                    'Start the Odoo service (without autostart)',
                    f"systemctl start '{config.odoo_service}'",
                ),
            ]
        )
    return commands


def plan_db_setup(
    config: InstanceConfig, ensure_remote_access: bool = True
) -> list[Command]:
    config.normalize_defaults()
    config.ensure_strong_secrets()
    config.validate_identifiers()
    role_sql = _db_role_create_if_missing_sql(config)

    commands: list[Command] = [
        Command(
            'Install PostgreSQL', "apt-get update && apt-get -y install postgresql"
        ),
        Command('Enable and start PostgreSQL', "systemctl enable --now postgresql"),
        Command(
            'Ensure PostgreSQL role (create if missing)',
            f"sudo -u postgres psql -v ON_ERROR_STOP=1 -c {shlex.quote(role_sql)}",
        ),
        Command(
            'Validate DB user login',
            _db_connectivity_check_command(config),
        ),
    ]

    if ensure_remote_access:
        commands.extend(
            [
                Command(
                    "Allow listen_addresses='*'",
                    'PG_CONF=$(sudo -u postgres psql -t -P format=unaligned -c "SHOW config_file;") && sed -ri "s/^#?\\s*listen_addresses\\s*=.*/listen_addresses = \'*\'/" "$PG_CONF"',
                ),
                Command(
                    'Add pg_hba rule for the app-server IP',
                    f'PG_HBA=$(sudo -u postgres psql -t -P format=unaligned -c "SHOW hba_file;") && grep -q "host    all     {config.db_user}     {config.app_server_ip}/32     scram-sha-256" "$PG_HBA" || echo "host    all     {config.db_user}     {config.app_server_ip}/32     scram-sha-256" | sudo tee -a "$PG_HBA" >/dev/null',
                ),
                Command('Restart PostgreSQL', "systemctl restart postgresql"),
            ]
        )

    return commands


def plan_ensure_db_role(config: InstanceConfig) -> list[Command]:
    config.normalize_defaults()
    config.ensure_strong_secrets()
    config.validate_identifiers()

    commands: list[Command] = []
    if _is_local_db_host(config.db_host):
        role_sql = _db_role_create_if_missing_sql(config)
        commands.append(
            Command(
                'Ensure local PostgreSQL role (create if missing)',
                f"sudo -u postgres psql -v ON_ERROR_STOP=1 -c {shlex.quote(role_sql)}",
            )
        )
    else:
        commands.append(
            Command(
                'Remote DB role info',
                "echo '[INFO] Remote DB host: role creation is skipped without remote admin credentials; the given user login will be validated.'",
            )
        )

    commands.append(
        Command(
            'Validate DB user login',
            _db_connectivity_check_command(config),
        )
    )
    return commands


def plan_nginx_http(
    config: InstanceConfig, nginx_version: tuple[int, int, int] | None = None
) -> list[Command]:
    # nginx_version is accepted for signature parity with plan_nginx_https; the
    # plain HTTP vhost listens on port 80 only and needs no http2 adaptation.
    site_available = f"/etc/nginx/sites-available/{config.nginx_http_name}"
    site_enabled_http = f"/etc/nginx/sites-enabled/{config.nginx_http_name}"
    site_enabled_https = f"/etc/nginx/sites-enabled/{config.nginx_https_name}"

    commands: list[Command] = [
        Command('Install Nginx', "apt-get update && apt-get -y install nginx"),
        Command('Enable Nginx', "systemctl enable --now nginx"),
    ]
    commands.extend(
        write_text_file_command(site_available, _nginx_http_content(config), "644")
    )
    commands.extend(
        [
            Command(
                'Disable the instance HTTPS vhost',
                f"rm -f '{site_enabled_https}'",
            ),
            Command(
                'Enable the instance HTTP vhost',
                f"ln -sf '{site_available}' '{site_enabled_http}'",
            ),
            Command('Validate Nginx', "nginx -t"),
            Command('Reload Nginx', "systemctl reload nginx"),
        ]
    )
    return commands


def plan_nginx_https(
    config: InstanceConfig, nginx_version: tuple[int, int, int] | None = None
) -> list[Command]:
    site_available = f"/etc/nginx/sites-available/{config.nginx_https_name}"
    site_enabled_http = f"/etc/nginx/sites-enabled/{config.nginx_http_name}"
    site_enabled_https = f"/etc/nginx/sites-enabled/{config.nginx_https_name}"

    commands: list[Command] = [
        Command('Install Nginx', "apt-get update && apt-get -y install nginx"),
        Command('Enable Nginx', "systemctl enable --now nginx"),
    ]
    commands.extend(
        write_text_file_command(
            site_available, _nginx_https_content(config, nginx_version), "644"
        )
    )
    commands.extend(
        [
            Command(
                'Disable the instance HTTP vhost', f"rm -f '{site_enabled_http}'"
            ),
            Command(
                'Enable the instance HTTPS vhost',
                f"ln -sf '{site_available}' '{site_enabled_https}'",
            ),
            Command('Validate Nginx', "nginx -t"),
            Command('Reload Nginx', "systemctl reload nginx"),
        ]
    )
    return commands


def plan_copy_custom_certs(
    config: InstanceConfig,
    cert_src: str,
    key_src: str,
    intermediate_src: str | None,
) -> list[Command]:
    commands: list[Command] = [
        Command(
            'Create dedicated SSL directory',
            f"install -d -m 750 -o root -g www-data '{config.nginx_ssl_dir}'",
        ),
        Command(
            'Copy server.crt',
            f"install -m 644 -o root -g www-data '{cert_src}' '{config.ssl_cert_file}'",
        ),
        Command(
            'Copy server.key',
            f"install -m 640 -o root -g www-data '{key_src}' '{config.ssl_key_file}'",
        ),
    ]

    if intermediate_src:
        commands.append(
            Command(
                'Copy intermediate.crt',
                f"install -m 644 -o root -g www-data '{intermediate_src}' '{config.ssl_intermediate_file}'",
            )
        )
        commands.append(
            Command(
                'Build fullchain (cert + intermediate)',
                "{ "
                + "awk 'BEGIN{in_cert=0} /-----BEGIN CERTIFICATE-----/{in_cert=1} in_cert{gsub(/\\r$/,\"\"); print} /-----END CERTIFICATE-----/{in_cert=0; print \"\"}' "
                + f"'{config.ssl_cert_file}'; "
                + "awk 'BEGIN{in_cert=0} /-----BEGIN CERTIFICATE-----/{in_cert=1} in_cert{gsub(/\\r$/,\"\"); print} /-----END CERTIFICATE-----/{in_cert=0; print \"\"}' "
                + f"'{config.ssl_intermediate_file}'; "
                + f"}} > '{config.ssl_fullchain_file}'",
            )
        )
    else:
        commands.append(
            Command(
                'Use server.crt as fullchain',
                f"cp '{config.ssl_cert_file}' '{config.ssl_fullchain_file}'",
            )
        )

    commands.extend(
        [
            Command(
                'Validate TLS private key',
                f"openssl pkey -in '{config.ssl_key_file}' -noout >/dev/null",
            ),
            Command(
                'Validate main TLS certificate',
                f"openssl x509 -in '{config.ssl_cert_file}' -noout >/dev/null",
            ),
            Command(
                'Validate KEY/CRT match',
                "CERT_FP=$(openssl x509 -in '"
                + config.ssl_cert_file
                + "' -pubkey -noout | openssl pkey -pubin -outform PEM 2>/dev/null | sha256sum | awk '{print $1}') && "
                + "KEY_FP=$(openssl pkey -in '"
                + config.ssl_key_file
                + "' -pubout -outform PEM 2>/dev/null | sha256sum | awk '{print $1}') && "
                + "test -n \"$CERT_FP\" -a -n \"$KEY_FP\" -a \"$CERT_FP\" = \"$KEY_FP\" "
                + "|| (echo '[ERROR] The private key does not match the selected public certificate.' && exit 1)",
            ),
            Command(
                'Validate TLS fullchain',
                f"openssl x509 -in '{config.ssl_fullchain_file}' -noout >/dev/null",
            ),
        ]
    )

    commands.extend(
        [
            Command(
                "Owner fullchain", f"chown root:www-data '{config.ssl_fullchain_file}'"
            ),
            Command('Permissions on fullchain', f"chmod 644 '{config.ssl_fullchain_file}'"),
        ]
    )
    return commands


def plan_ensure_self_signed_certs(config: InstanceConfig) -> list[Command]:
    return [
        Command(
            'Ensure dedicated SSL directory',
            f"install -d -m 750 -o root -g www-data '{config.nginx_ssl_dir}'",
        ),
        Command(
            'Generate self-signed if missing (server.key/fullchain)',
            "if [ -s '"
            + config.ssl_key_file
            + "' ] && [ -s '"
            + config.ssl_fullchain_file
            + "' ]; then "
            + "echo '[INFO] Existing self-signed certificate, reusing it.'; "
            + "else "
            + "command -v openssl >/dev/null 2>&1 || (apt-get update && apt-get -y install openssl); "
            + "openssl req -x509 -nodes -newkey rsa:2048 -sha256 -days 825 "
            + "-keyout '"
            + config.ssl_key_file
            + "' "
            + "-out '"
            + config.ssl_cert_file
            + "' "
            + "-subj '/CN="
            + config.domain
            + "'; "
            + "cp '"
            + config.ssl_cert_file
            + "' '"
            + config.ssl_fullchain_file
            + "'; "
            + "fi",
        ),
        Command(
            'Adjust self-signed certificate permissions',
            f"chown root:www-data '{config.ssl_key_file}' '{config.ssl_cert_file}' '{config.ssl_fullchain_file}' && chmod 640 '{config.ssl_key_file}' && chmod 644 '{config.ssl_cert_file}' '{config.ssl_fullchain_file}'",
        ),
    ]


def plan_backup_retention(
    config: InstanceConfig, backup_dir: str, keep: int
) -> list[Command]:
    """Delete an instance's oldest backup artifacts, keeping the `keep` newest of
    each kind (DB dumps and filestore archives)."""
    qdir = shlex.quote(backup_dir)
    commands: list[Command] = []
    for pattern, label in (
        (f"{config.instance}_*.dump", 'DB dumps'),
        (f"{config.instance}_*.filestore.tar.gz", 'filestore archives'),
    ):
        commands.append(
            Command(
                tf('Delete old {} (keep the {} most recent)', label, keep),
                f"ls -1t {qdir}/{pattern} 2>/dev/null | tail -n +{keep + 1} | xargs -r rm -f",
            )
        )
    return commands


def _scheduled_backup_script(
    config: InstanceConfig,
    db_name: str,
    backup_dir: str,
    filestore_dir: str,
    keep: int,
    include_filestore: bool,
) -> str:
    inst = config.instance
    filestore_block = ""
    if include_filestore:
        filestore_block = f'''
if [ -d "$FILESTORE" ]; then
  TMPF="$BACKUP_DIR/{inst}_${{TS}}.filestore.tar.gz.partial"
  tar -czf "$TMPF" -C "$FILESTORE" . && mv "$TMPF" "$BACKUP_DIR/{inst}_${{TS}}.filestore.tar.gz"
fi
ls -1t "$BACKUP_DIR/{inst}"_*.filestore.tar.gz 2>/dev/null | tail -n +$(({keep}+1)) | xargs -r rm -f
'''
    return f'''#!/usr/bin/env bash
set -euo pipefail
BACKUP_DIR="{backup_dir}"
FILESTORE="{filestore_dir}"
TS=$(date +%Y%m%d_%H%M%S)
mkdir -p "$BACKUP_DIR"
TMP="$BACKUP_DIR/{inst}_${{TS}}.dump.partial"
sudo -u postgres pg_dump -Fc {shlex.quote(db_name)} > "$TMP" && mv "$TMP" "$BACKUP_DIR/{inst}_${{TS}}.dump"
ls -1t "$BACKUP_DIR/{inst}"_*.dump 2>/dev/null | tail -n +$(({keep}+1)) | xargs -r rm -f
{filestore_block}'''


def _scheduled_backup_service(name: str, script_path: str, instance: str) -> str:
    return f'''[Unit]
Description=Scheduled Odoo backup ({instance})
After=postgresql.service

[Service]
Type=oneshot
ExecStart={script_path}
'''


def _scheduled_backup_timer(name: str, oncalendar: str, instance: str) -> str:
    return f'''[Unit]
Description=Odoo backup timer ({instance})

[Timer]
OnCalendar={oncalendar}
Persistent=true

[Install]
WantedBy=timers.target
'''


def plan_scheduled_backup(
    config: InstanceConfig,
    *,
    db_name: str,
    backup_dir: str,
    filestore_dir: str,
    oncalendar: str,
    keep: int,
    include_filestore: bool,
) -> list[Command]:
    """Install a systemd service + timer that backs up the instance's DB (via
    local ``sudo -u postgres pg_dump``) and, optionally, its filestore, with
    retention, on the given ``OnCalendar`` schedule."""
    name = f"odoo-backup-{config.instance}"
    script_path = f"/usr/local/sbin/{name}.sh"
    service_path = f"/etc/systemd/system/{name}.service"
    timer_path = f"/etc/systemd/system/{name}.timer"

    commands: list[Command] = []
    commands.extend(
        write_text_file_command(
            script_path,
            _scheduled_backup_script(config, db_name, backup_dir, filestore_dir, keep, include_filestore),
            "750",
        )
    )
    commands.extend(
        write_text_file_command(service_path, _scheduled_backup_service(name, script_path, config.instance), "644")
    )
    commands.extend(
        write_text_file_command(timer_path, _scheduled_backup_timer(name, oncalendar, config.instance), "644")
    )
    commands.append(Command('Reload systemd', "systemctl daemon-reload"))
    commands.append(
        Command('Enable and start backup timer', f"systemctl enable --now {name}.timer")
    )
    return commands


def plan_remove_scheduled_backup(config: InstanceConfig) -> list[Command]:
    name = f"odoo-backup-{config.instance}"
    return [
        Command('Stop and disable timer', f"systemctl disable --now {name}.timer || true"),
        Command(
            'Remove backup units and script',
            f"rm -f /etc/systemd/system/{name}.timer /etc/systemd/system/{name}.service "
            f"/usr/local/sbin/{name}.sh",
        ),
        Command('Reload systemd', "systemctl daemon-reload"),
    ]


def plan_ufw_base_setup(
    *,
    ssh_port: int = 22,
    allow_http: bool = True,
    allow_https: bool = True,
    pg_from_ip: str = "",
) -> list[Command]:
    """Install UFW and apply a secure baseline: deny incoming / allow outgoing,
    allow SSH (before enabling, to avoid lock-out), HTTP/HTTPS, and optionally
    PostgreSQL from a single app-server IP; then enable UFW."""
    commands: list[Command] = [
        Command(
            'Ensure UFW is installed',
            "command -v ufw >/dev/null 2>&1 || (apt-get update && apt-get -y install ufw)",
        ),
        Command('Default policy: deny incoming', "ufw default deny incoming"),
        Command('Default policy: allow outgoing', "ufw default allow outgoing"),
        Command(tf('Allow SSH (port {})', ssh_port), f"ufw allow {int(ssh_port)}/tcp"),
    ]
    if allow_http:
        commands.append(Command('Allow HTTP (80)', "ufw allow 80/tcp"))
    if allow_https:
        commands.append(Command('Allow HTTPS (443)', "ufw allow 443/tcp"))
    if pg_from_ip:
        commands.append(
            Command(
                tf('Allow PostgreSQL (5432) from {}', pg_from_ip),
                f"ufw allow from {shlex.quote(pg_from_ip)} to any port 5432 proto tcp",
            )
        )
    commands.append(Command('Enable UFW', "ufw --force enable"))
    return commands


def plan_ufw_allow_port(port: int, proto: str) -> list[Command]:
    proto = "udp" if proto == "udp" else "tcp"
    return [Command(tf('Allow {}/{}', int(port), proto), f"ufw allow {int(port)}/{proto}")]


def plan_ufw_delete_rule(number: int) -> list[Command]:
    return [
        Command(
            tf('Delete UFW rule #{}', int(number)),
            f"ufw --force delete {int(number)}",
        )
    ]


_WKHTMLTOPDF_BASE_URL = (
    "https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6.1-3"
)
# Detected OS codename -> (asset filename, sha256). amd64, Qt-patched 0.12.6.1-3.
# The jammy build is verified against Odoo's own pinned checksum (its SHA-1
# 967390a759707337b46d1c02452e2bb6b2dc6d59 matches the Odoo 18 Dockerfile) and
# also runs on noble (24.04). Codenames without a compatible asset resolve to
# None so the caller recommends the distro package or skip — never a guessed URL.
_WKHTMLTOPDF_ASSETS: dict[str, tuple[str, str]] = {
    "jammy": (
        "wkhtmltox_0.12.6.1-3.jammy_amd64.deb",
        "4f723b2691ad8638a9df960e0421d346d7315083e3583a334f33362280ddba15",
    ),
    "noble": (
        "wkhtmltox_0.12.6.1-3.jammy_amd64.deb",
        "4f723b2691ad8638a9df960e0421d346d7315083e3583a334f33362280ddba15",
    ),
    "bookworm": (
        "wkhtmltox_0.12.6.1-3.bookworm_amd64.deb",
        "98ba0d157b50d36f23bd0dedf4c0aa28c7b0c50fcdcdc54aa5b6bbba81a3941d",
    ),
    "bullseye": (
        "wkhtmltox_0.12.6.1-3.bullseye_amd64.deb",
        "9c687f0c58cf50e01f2a6375d2e34372f8feeec56a84690ea113d298fccadd98",
    ),
}


def resolve_wkhtmltopdf_asset(codename: str) -> tuple[str, str, str] | None:
    """``(url, filename, sha256)`` for the patched wkhtmltopdf matching ``codename``,
    or ``None`` when no compatible verified asset is pinned (the caller then
    recommends the distro package or skip; it never guesses a URL)."""
    entry = _WKHTMLTOPDF_ASSETS.get((codename or "").strip().lower())
    if not entry:
        return None
    filename, sha256 = entry
    return f"{_WKHTMLTOPDF_BASE_URL}/{filename}", filename, sha256


def plan_install_wkhtmltopdf(mode: str, codename: str = "") -> list[Command]:
    """Plan a wkhtmltopdf install.

    ``mode == "patched"``: download the codename's pinned Qt-patched ``.deb``,
    verify its SHA-256, and install only on a match. ``mode == "distro"``: the apt
    package (un-patched, reduced fidelity). Any other mode (or an unmapped codename
    for ``patched``): no commands.
    """
    if mode == "distro":
        return [
            Command(
                'Install distro wkhtmltopdf (un-patched, reduced fidelity)',
                "apt-get update && apt-get -y install wkhtmltopdf",
            )
        ]
    if mode != "patched":
        return []
    asset = resolve_wkhtmltopdf_asset(codename)
    if asset is None:
        return []
    url, filename, sha256 = asset
    tmp = f"/tmp/{filename}"
    return [
        Command(
            'Ensure curl is available',
            "command -v curl >/dev/null 2>&1 || (apt-get update && apt-get -y install curl)",
        ),
        Command(
            tf('Download patched wkhtmltopdf ({})', filename),
            f"curl -fSL -o {shlex.quote(tmp)} {shlex.quote(url)}",
        ),
        Command(
            'Verify wkhtmltopdf SHA-256 (aborts on mismatch)',
            f"echo {shlex.quote(sha256 + '  ' + tmp)} | sha256sum -c -",
        ),
        Command(
            'Install verified wkhtmltopdf .deb',
            f"apt-get update && apt-get -y install {shlex.quote(tmp)}",
        ),
        Command('Remove downloaded wkhtmltopdf .deb', f"rm -f {shlex.quote(tmp)}"),
    ]


def posture_rows(
    *,
    instance: str,
    conf_values: dict[str, str],
    wkhtmltopdf_ver: str | None,
    cpu_count: int | None = None,
) -> list[tuple[str, str, str]]:
    """Pure security/production posture evaluation over a read ``odoo.conf`` plus
    host facts. Returns ``(state, check, detail)`` rows (state ∈ OK/WARN/INFO),
    shared by the management posture view and the server-audit report."""
    rows: list[tuple[str, str, str]] = []

    list_db = conf_values.get("list_db", "").strip().lower()
    manager_exposed = list_db in {"", "true", "1", "yes"}
    if manager_exposed:
        rows.append((
            "WARN",
            "Database manager (list_db)",
            "exposed — set list_db = False for production (and a dbfilter)",
        ))
    else:
        rows.append(("OK", "Database manager (list_db)", "disabled (list_db = False)"))

    dbfilter = conf_values.get("dbfilter", "").strip()
    if dbfilter:
        rows.append(("OK", "dbfilter", dbfilter))
    else:
        rows.append((
            "WARN" if manager_exposed else "INFO",
            "dbfilter",
            "not set — bind the instance to its database(s)",
        ))

    admin = conf_values.get("admin_passwd", "").strip()
    if admin == instance:
        rows.append((
            "WARN",
            "Master password (admin_passwd)",
            "equals the instance name — guessable",
        ))
    elif admin.startswith("$"):
        rows.append(("OK", "Master password (admin_passwd)", "hashed"))
    elif admin:
        rows.append(("OK", "Master password (admin_passwd)", "set (non-default)"))
    else:
        rows.append(("INFO", "Master password (admin_passwd)", "not found in config"))

    db_password = conf_values.get("db_password", "").strip()
    if db_password == instance:
        rows.append(("WARN", "DB password", "equals the instance name — guessable"))
    elif db_password:
        rows.append(("OK", "DB password", "set (non-default)"))
    else:
        rows.append(("INFO", "DB password", "not found in config"))

    if not wkhtmltopdf_ver:
        rows.append(("WARN", "wkhtmltopdf", "not installed — PDF reports will fail"))
    else:
        patched = "with patched qt" in wkhtmltopdf_ver.lower()
        detail = wkhtmltopdf_ver if patched else f"{wkhtmltopdf_ver} (un-patched — reports may be degraded)"
        rows.append(("OK" if patched else "WARN", "wkhtmltopdf", detail))

    workers_raw = conf_values.get("workers", "").strip()
    if workers_raw.isdigit():
        workers = int(workers_raw)
        if workers == 0:
            rows.append(("WARN", "workers", "0 (threaded/dev mode) — set > 0 for production"))
        elif cpu_count:
            suggested = cpu_count * 2 + 1
            state = "OK" if workers <= suggested else "INFO"
            rows.append((state, "workers", tf("{} (detected {} CPU → suggested {})", workers, cpu_count, suggested)))
        else:
            rows.append(("OK", "workers", workers_raw))
    else:
        rows.append(("INFO", "workers", "not set"))

    db_host = conf_values.get("db_host", "")
    if _is_local_db_host(db_host):
        rows.append(("OK", "db_sslmode", "local DB (SSL mode not required)"))
    else:
        sslmode = conf_values.get("db_sslmode", "").strip().lower()
        if sslmode in {"require", "verify-ca", "verify-full"}:
            rows.append(("OK", "db_sslmode (remote DB)", sslmode))
        else:
            rows.append((
                "WARN",
                "db_sslmode (remote DB)",
                f"{sslmode or 'unset'} — remote DB traffic may be unencrypted; use require or stricter",
            ))

    if conf_values.get("proxy_mode", "").strip().lower() in {"true", "1", "yes"}:
        rows.append(("OK", "proxy_mode", "True"))
    else:
        rows.append(("WARN", "proxy_mode", "not True — required behind Nginx"))

    return rows


def pretty_paths(config: InstanceConfig) -> list[tuple[str, str]]:
    return [
        ("Instance", config.instance),
        ("Odoo user", config.odoo_user),
        ("Odoo home", config.odoo_home),
        ("Odoo conf", config.odoo_conf_file),
        ("Service", config.odoo_service),
        ("Nginx HTTP conf", f"/etc/nginx/sites-available/{config.nginx_http_name}"),
        ("Nginx HTTPS conf", f"/etc/nginx/sites-available/{config.nginx_https_name}"),
        ("SSL dir", config.nginx_ssl_dir),
        ('DB user', config.db_user),
        ("DB name", config.db_name),
    ]
