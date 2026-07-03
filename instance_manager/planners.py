from __future__ import annotations

import re
import shlex

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
        f"RAISE NOTICE 'Role {db_user_literal} ya existe; se reutiliza sin cambiar contraseña.'; "
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
    return f"""[options]
admin_passwd = {config.odoo_admin_passwd}
list_db = True

addons_path = {config.odoo_home}/odoo/addons,{config.odoo_home}/addons-oca,{config.odoo_home}/addons-custom

http_interface = 127.0.0.1
http_port = {config.http_port}
gevent_port = {config.gevent_port}
proxy_mode = True

logfile = {config.odoo_log_file}
logrotate = True

workers = 4
max_cron_threads = 2
limit_memory_soft = 2147483648
limit_memory_hard = 2684354560
limit_time_cpu = 3600
limit_time_real = 7200

db_host = {config.db_host}
db_port = {config.db_port}
db_user = {config.db_user}
db_password = {config.db_password}
"""


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

  location /websocket {{
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


def _nginx_https_content(config: InstanceConfig) -> str:
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
  listen 443 ssl http2;
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

  location /websocket {{
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
            description=f"Escribir {target_path}",
            command=f"cat > '{target_path}' <<'EOF'\n{content}\nEOF",
        ),
        Command(
            description=f"Permisos {mode} en {target_path}",
            command=f"chmod {mode} '{target_path}'",
        ),
    ]


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
        Command("Actualizar paquetes", "apt-get update"),
        Command("Instalar fail2ban", "apt-get -y install fail2ban"),
        Command("Crear /etc/fail2ban/jail.d", "mkdir -p /etc/fail2ban/jail.d"),
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
            Command("Validar configuración fail2ban", "fail2ban-client -t"),
            Command("Habilitar y arrancar fail2ban", "systemctl enable --now fail2ban"),
            Command("Reiniciar fail2ban", "systemctl restart fail2ban"),
            Command(
                "Esperar socket fail2ban listo",
                "for i in $(seq 1 15); do fail2ban-client ping >/dev/null 2>&1 && exit 0; sleep 1; done; "
                "echo '[ERROR] fail2ban activo pero socket no disponible tras espera.'; "
                "systemctl status fail2ban --no-pager -n 50 || true; exit 1",
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
        Command("Asegurar fail2ban instalado", "apt-get update && apt-get -y install fail2ban"),
        Command("Crear directorios fail2ban", "mkdir -p /etc/fail2ban/filter.d /etc/fail2ban/jail.d"),
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
            Command("Validar log de instancia", f"test -f {shlex.quote(log_path)}"),
            Command(
                "Probar regex fail2ban con log Odoo",
                f"fail2ban-regex {shlex.quote(log_path)} {shlex.quote(filter_path)}",
            ),
            Command("Validar configuración fail2ban", "fail2ban-client -t"),
            Command("Habilitar y arrancar fail2ban", "systemctl enable --now fail2ban"),
            Command("Reiniciar fail2ban", "systemctl restart fail2ban"),
            Command(
                "Esperar socket fail2ban listo",
                "for i in $(seq 1 15); do fail2ban-client ping >/dev/null 2>&1 && exit 0; sleep 1; done; "
                "echo '[ERROR] fail2ban activo pero socket no disponible tras espera.'; "
                "systemctl status fail2ban --no-pager -n 50 || true; exit 1",
            ),
        ]
    )
    return commands


def plan_fail2ban_ensure_odoo_filter() -> list[Command]:
    filter_path = "/etc/fail2ban/filter.d/odoo-auth.conf"

    commands: list[Command] = [
        Command("Crear directorio filtros fail2ban", "mkdir -p /etc/fail2ban/filter.d"),
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
    config.validate_identifiers()
    commands: list[Command] = [
        Command("Actualizar paquetes", "apt-get update"),
        Command(
            "Instalar dependencias base Odoo",
            "apt-get -y install git build-essential pkg-config python3 python3-venv python3-dev python3-pip "
            "libpq-dev libldap2-dev libsasl2-dev libssl-dev libffi-dev libxml2-dev libxslt1-dev "
            "libjpeg-dev zlib1g-dev libtiff-dev libopenjp2-7-dev liblcms2-dev libwebp-dev "
            "libharfbuzz-dev libfribidi-dev fontconfig postgresql-client xfonts-75dpi xfonts-base",
        ),
        Command(
            "Crear usuario de sistema (si falta)",
            f"id -u '{config.odoo_user}' >/dev/null 2>&1 || adduser --system --home '{config.odoo_home}' --group '{config.odoo_user}'",
        ),
        Command(
            "Crear directorios instancia",
            f"mkdir -p '{config.odoo_home}/odoo' '{config.odoo_home}/addons-oca' '{config.odoo_home}/addons-custom' '{config.odoo_conf_dir}' /var/log/odoo",
        ),
        Command(
            "Ajustar ownership base",
            f"chown -R '{config.odoo_user}:{config.odoo_user}' '{config.odoo_home}' /var/log/odoo",
        ),
        Command("Permisos carpeta config", f"chmod 750 '{config.odoo_conf_dir}'"),
        Command(
            "Clonar repo Odoo si falta",
            f"sudo -u '{config.odoo_user}' bash -lc \"test -d '{config.odoo_home}/odoo/.git' || git clone --depth 1 --branch '{config.repo_branch}' https://github.com/odoo/odoo.git '{config.odoo_home}/odoo'\"",
        ),
        Command(
            "Crear/actualizar venv e instalar requirements",
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
    commands.append(Command("Recargar systemd", "systemctl daemon-reload"))
    if service_autostart:
        commands.append(
            Command(
                "Habilitar y arrancar servicio Odoo",
                f"systemctl enable --now '{config.odoo_service}'",
            )
        )
    else:
        commands.extend(
            [
                Command(
                    "Deshabilitar autoarranque de servicio Odoo",
                    f"systemctl disable '{config.odoo_service}' || true",
                ),
                Command(
                    "Arrancar servicio Odoo (sin autoarranque)",
                    f"systemctl start '{config.odoo_service}'",
                ),
            ]
        )
    return commands


def plan_db_setup(
    config: InstanceConfig, ensure_remote_access: bool = True
) -> list[Command]:
    config.normalize_defaults()
    config.validate_identifiers()
    role_sql = _db_role_create_if_missing_sql(config)

    commands: list[Command] = [
        Command(
            "Instalar PostgreSQL", "apt-get update && apt-get -y install postgresql"
        ),
        Command("Habilitar y arrancar PostgreSQL", "systemctl enable --now postgresql"),
        Command(
            "Asegurar rol PostgreSQL (crear si falta)",
            f"sudo -u postgres psql -v ON_ERROR_STOP=1 -c {shlex.quote(role_sql)}",
        ),
        Command(
            "Validar login del usuario DB",
            _db_connectivity_check_command(config),
        ),
    ]

    if ensure_remote_access:
        commands.extend(
            [
                Command(
                    "Permitir listen_addresses='*'",
                    'PG_CONF=$(sudo -u postgres psql -t -P format=unaligned -c "SHOW config_file;") && sed -ri "s/^#?\\s*listen_addresses\\s*=.*/listen_addresses = \'*\'/" "$PG_CONF"',
                ),
                Command(
                    "Añadir regla pg_hba por IP app server",
                    f'PG_HBA=$(sudo -u postgres psql -t -P format=unaligned -c "SHOW hba_file;") && grep -q "host    all     {config.db_user}     {config.app_server_ip}/32     scram-sha-256" "$PG_HBA" || echo "host    all     {config.db_user}     {config.app_server_ip}/32     scram-sha-256" | sudo tee -a "$PG_HBA" >/dev/null',
                ),
                Command("Reiniciar PostgreSQL", "systemctl restart postgresql"),
            ]
        )

    return commands


def plan_ensure_db_role(config: InstanceConfig) -> list[Command]:
    config.normalize_defaults()
    config.validate_identifiers()

    commands: list[Command] = []
    if _is_local_db_host(config.db_host):
        role_sql = _db_role_create_if_missing_sql(config)
        commands.append(
            Command(
                "Asegurar rol PostgreSQL local (crear si falta)",
                f"sudo -u postgres psql -v ON_ERROR_STOP=1 -c {shlex.quote(role_sql)}",
            )
        )
    else:
        commands.append(
            Command(
                "Info rol DB remoto",
                "echo '[INFO] DB host remoto: se omite creación de rol sin credenciales admin remotas; se validará login del usuario indicado.'",
            )
        )

    commands.append(
        Command(
            "Validar login del usuario DB",
            _db_connectivity_check_command(config),
        )
    )
    return commands


def plan_nginx_http(config: InstanceConfig) -> list[Command]:
    site_available = f"/etc/nginx/sites-available/{config.nginx_http_name}"
    site_enabled_http = f"/etc/nginx/sites-enabled/{config.nginx_http_name}"
    site_enabled_https = f"/etc/nginx/sites-enabled/{config.nginx_https_name}"

    commands: list[Command] = [
        Command("Instalar Nginx", "apt-get update && apt-get -y install nginx"),
        Command("Habilitar Nginx", "systemctl enable --now nginx"),
    ]
    commands.extend(
        write_text_file_command(site_available, _nginx_http_content(config), "644")
    )
    commands.extend(
        [
            Command(
                "Desactivar vhost HTTPS de la instancia",
                f"rm -f '{site_enabled_https}'",
            ),
            Command(
                "Activar vhost HTTP de la instancia",
                f"ln -sf '{site_available}' '{site_enabled_http}'",
            ),
            Command("Validar Nginx", "nginx -t"),
            Command("Recargar Nginx", "systemctl reload nginx"),
        ]
    )
    return commands


def plan_nginx_https(config: InstanceConfig) -> list[Command]:
    site_available = f"/etc/nginx/sites-available/{config.nginx_https_name}"
    site_enabled_http = f"/etc/nginx/sites-enabled/{config.nginx_http_name}"
    site_enabled_https = f"/etc/nginx/sites-enabled/{config.nginx_https_name}"

    commands: list[Command] = [
        Command("Instalar Nginx", "apt-get update && apt-get -y install nginx"),
        Command("Habilitar Nginx", "systemctl enable --now nginx"),
    ]
    commands.extend(
        write_text_file_command(site_available, _nginx_https_content(config), "644")
    )
    commands.extend(
        [
            Command(
                "Desactivar vhost HTTP de la instancia", f"rm -f '{site_enabled_http}'"
            ),
            Command(
                "Activar vhost HTTPS de la instancia",
                f"ln -sf '{site_available}' '{site_enabled_https}'",
            ),
            Command("Validar Nginx", "nginx -t"),
            Command("Recargar Nginx", "systemctl reload nginx"),
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
            "Crear directorio SSL dedicado",
            f"install -d -m 750 -o root -g www-data '{config.nginx_ssl_dir}'",
        ),
        Command(
            "Copiar server.crt",
            f"install -m 644 -o root -g www-data '{cert_src}' '{config.ssl_cert_file}'",
        ),
        Command(
            "Copiar server.key",
            f"install -m 640 -o root -g www-data '{key_src}' '{config.ssl_key_file}'",
        ),
    ]

    if intermediate_src:
        commands.append(
            Command(
                "Copiar intermediate.crt",
                f"install -m 644 -o root -g www-data '{intermediate_src}' '{config.ssl_intermediate_file}'",
            )
        )
        commands.append(
            Command(
                "Construir fullchain (cert + intermediate)",
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
                "Usar server.crt como fullchain",
                f"cp '{config.ssl_cert_file}' '{config.ssl_fullchain_file}'",
            )
        )

    commands.extend(
        [
            Command(
                "Validar clave privada TLS",
                f"openssl pkey -in '{config.ssl_key_file}' -noout >/dev/null",
            ),
            Command(
                "Validar certificado principal TLS",
                f"openssl x509 -in '{config.ssl_cert_file}' -noout >/dev/null",
            ),
            Command(
                "Validar correspondencia KEY/CRT",
                "CERT_FP=$(openssl x509 -in '"
                + config.ssl_cert_file
                + "' -pubkey -noout | openssl pkey -pubin -outform PEM 2>/dev/null | sha256sum | awk '{print $1}') && "
                + "KEY_FP=$(openssl pkey -in '"
                + config.ssl_key_file
                + "' -pubout -outform PEM 2>/dev/null | sha256sum | awk '{print $1}') && "
                + "test -n \"$CERT_FP\" -a -n \"$KEY_FP\" -a \"$CERT_FP\" = \"$KEY_FP\" "
                + "|| (echo '[ERROR] La clave privada no corresponde con el certificado público seleccionado.' && exit 1)",
            ),
            Command(
                "Validar fullchain TLS",
                f"openssl x509 -in '{config.ssl_fullchain_file}' -noout >/dev/null",
            ),
        ]
    )

    commands.extend(
        [
            Command(
                "Owner fullchain", f"chown root:www-data '{config.ssl_fullchain_file}'"
            ),
            Command("Permisos fullchain", f"chmod 644 '{config.ssl_fullchain_file}'"),
        ]
    )
    return commands


def plan_ensure_self_signed_certs(config: InstanceConfig) -> list[Command]:
    return [
        Command(
            "Asegurar directorio SSL dedicado",
            f"install -d -m 750 -o root -g www-data '{config.nginx_ssl_dir}'",
        ),
        Command(
            "Generar autofirmado si falta (server.key/fullchain)",
            "if [ -s '"
            + config.ssl_key_file
            + "' ] && [ -s '"
            + config.ssl_fullchain_file
            + "' ]; then "
            + "echo '[INFO] Certificado autofirmado existente, se reutiliza.'; "
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
            "Ajustar permisos de certificados autofirmados",
            f"chown root:www-data '{config.ssl_key_file}' '{config.ssl_cert_file}' '{config.ssl_fullchain_file}' && chmod 640 '{config.ssl_key_file}' && chmod 644 '{config.ssl_cert_file}' '{config.ssl_fullchain_file}'",
        ),
    ]


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
        ("DB user", config.db_user),
        ("DB name", config.db_name),
    ]
