from __future__ import annotations

import re
import shlex

from . import support
from .i18n import tf
from .models import InstanceConfig, host_cidr
from .system import Command, mask, pg_env


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


# The pg_hba rule the tool writes asks for scram-sha-256, and a password stored as
# md5 cannot pass it. PostgreSQL 13 (Debian 11) still stores md5 by default; 14 and
# later store scram. Set for the session that sets the password.
SCRAM = "SET password_encryption = 'scram-sha-256'; "


def _dollar_tag(*bodies: str) -> str:
    """A dollar-quote tag that none of ``bodies`` contains: a password holding ``$$``
    would otherwise end the quoted block early."""
    index = 0
    while any(f"$oim{index}$" in body for body in bodies):
        index += 1
    return f"$oim{index}$"


def _db_role_create_if_missing_sql(config: InstanceConfig, reset_password: bool = False) -> str:
    """Create the role with the password, or — when it exists — keep it, setting the
    password only when ``reset_password`` (the operator chose to)."""
    db_user_literal = _sql_literal(config.db_user)
    db_password_literal = _sql_literal(config.db_password)
    tag = _dollar_tag(db_password_literal)
    return (
        SCRAM + f"DO {tag} "
        "BEGIN "
        f"IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='{db_user_literal}') THEN "
        f"CREATE ROLE {config.db_user} WITH LOGIN CREATEDB PASSWORD '{db_password_literal}'; "
        "ELSE "
        + (f"ALTER ROLE {config.db_user} WITH LOGIN CREATEDB PASSWORD '{db_password_literal}'; "
           f"RAISE NOTICE 'Role {db_user_literal} already exists; its password is set to the new one.'; "
           if reset_password else
           f"ALTER ROLE {config.db_user} WITH LOGIN CREATEDB; "
           f"RAISE NOTICE 'Role {db_user_literal} already exists; reusing it without changing the password.'; ")
        +
        "END IF; "
        "END "
        f"{tag};"
    )


def _db_connectivity_check(config: InstanceConfig) -> Command:
    """Log in as the instance's role, the way Odoo will: TCP for a local host, and
    the SSL mode odoo.conf sets — checked against the CA where libpq looks for the
    instance user's (``~/.postgresql/root.crt``)."""
    check_host = config.db_host
    if _is_local_db_host(check_host):
        check_host = "127.0.0.1"
    env = pg_env(config.db_password)
    if config.db_sslmode:
        env["PGSSLMODE"] = config.db_sslmode
        if config.db_sslmode.startswith("verify"):
            env["PGSSLROOTCERT"] = f"{config.odoo_home}/.postgresql/root.crt"
    return Command(
        'Validate DB user login',
        f"psql -X -h {shlex.quote(check_host)} -p {int(config.db_port)} -U {shlex.quote(config.db_user)} "
        "-d postgres -tAc 'SELECT 1;' >/dev/null",
        env=env,
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
    if config.data_dir:
        lines += ["", f"data_dir = {config.data_dir}"]
    # A production database never wants demo data; Odoo <= 18 loads it into a new
    # database (CLI `-i base`, or the database manager) unless told not to.
    if config.odoo_major <= support.DEMO_BY_DEFAULT_LAST_MAJOR:
        lines.append("without_demo = all")
    return "\n".join(lines) + "\n"


# Keys an operator may have tuned by hand whose current value a regeneration keeps;
# every other key the tool writes takes the tool's value, and keys it does not
# write are carried over unchanged.
CONF_KEYS_KEPT_ON_UPDATE = ("addons_path", "data_dir", "logfile", "http_interface", "without_demo")
# The bus port has two names; writing one drops the other.
_BUS_PORT_KEYS = ("gevent_port", "longpolling_port")


def _conf_key(line: str) -> str | None:
    if "=" not in line or line.lstrip().startswith(("#", ";", "[")):
        return None
    return line.split("=", 1)[0].strip()


def _conf_line(key: str, value: str) -> str:
    """``key = value``, a value of several lines continued as Odoo's parser reads it."""
    return f"{key} = " + value.replace("\n", "\n    ")


def render_merged_odoo_conf(config: InstanceConfig, existing: dict[str, str], other_sections: str = "") -> str:
    """The instance's ``odoo.conf`` regenerated without losing what it held: the
    keys in ``CONF_KEYS_KEPT_ON_UPDATE`` keep their current value, every key the
    tool does not write (``smtp_*``, ``server_wide_modules``, ``db_name``, …) is
    carried over below, and the file's other sections (``[queue_job]``, …) follow as
    they were. Pure — ``existing`` is the parsed ``[options]`` of the current file."""
    lines = _odoo_conf_content(config).rstrip("\n").split("\n")
    written: set[str] = set()
    for index, line in enumerate(lines):
        key = _conf_key(line)
        if key is None:
            continue
        written.add(key)
        if key in CONF_KEYS_KEPT_ON_UPDATE and existing.get(key, "") != "":
            lines[index] = _conf_line(key, existing[key])
    for key in CONF_KEYS_KEPT_ON_UPDATE:
        if key not in written and existing.get(key, "") != "":
            lines.append(_conf_line(key, existing[key]))
            written.add(key)
    if written & set(_BUS_PORT_KEYS):
        written |= set(_BUS_PORT_KEYS)
    carried = [_conf_line(key, value) for key, value in existing.items() if key not in written]
    if carried:
        lines += ["", "; kept from the previous configuration", *carried]
    if other_sections:
        lines += ["", other_sections]
    return "\n".join(lines) + "\n"


def plan_update_instance_config(
    config: InstanceConfig,
    existing: dict[str, str],
    *,
    new_db_password: bool,
    restart: bool,
    other_sections: str = "",
) -> list[Command]:
    """Rewrite an existing instance's ``odoo.conf`` (merged) and unit, and apply them.

    Nothing is reinstalled — no apt, clone or pip, which could move setuptools under
    an Odoo that needs it pinned. A new DB password is set on the local role too, or
    the next start could not connect. The service is restarted when it runs, since
    ``systemctl start`` on a running unit loads nothing."""
    commands = write_text_file_command(
        config.odoo_conf_file, render_merged_odoo_conf(config, existing, other_sections), "640",
        secrets=(config.odoo_admin_passwd, config.db_password,
                 *(value for key, value in existing.items() if "pass" in key or "secret" in key)),
    )
    commands.append(
        Command("Owner config Odoo", f"chown root:{shlex.quote(config.odoo_user)} {shlex.quote(config.odoo_conf_file)}")
    )
    service_path = f"/etc/systemd/system/{config.odoo_service}.service"
    commands += write_text_file_command(service_path, _systemd_content(config), "644")
    commands.append(Command('Reload systemd', "systemctl daemon-reload"))
    if new_db_password and not config.is_remote_db_host:
        sql = f"{SCRAM}ALTER ROLE \"{config.db_user}\" WITH PASSWORD '{_sql_literal(config.db_password)}';"
        commands.append(
            _psql_stdin_command(
                f"{_local_psql(config)} -q -v ON_ERROR_STOP=1", sql, (config.db_password,),
                'Set the new password on the local PostgreSQL role',
            )
        )
    if restart:
        commands.append(
            Command('Restart the Odoo service to load the configuration', f"systemctl restart {shlex.quote(config.odoo_service)}")
        )
    return commands


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
    """The unit, after Odoo's own (debian/odoo.service): ``KillMode=mixed`` lets the
    master stop its workers itself. A local database is waited for."""
    after = "network-online.target" + ("" if config.is_remote_db_host else " postgresql.service")
    return f"""[Unit]
Description=Odoo {config.version} ({config.instance})
Wants=network-online.target
After={after}

[Service]
Type=simple
User={config.odoo_user}
Group={config.odoo_user}
WorkingDirectory={config.odoo_home}/odoo
ExecStart={config.odoo_home}/venv/bin/python3 {config.odoo_home}/odoo/odoo-bin -c {config.odoo_conf_file}
KillMode=mixed
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


# The TLS settings and per-location headers of Odoo's own deployment guide
# (odoo/documentation 18.0 content/administration/on_premise/deploy.rst): HSTS, and
# the session cookie marked Secure — Odoo sets it without `secure`, so without this
# it could travel over plain HTTP before the redirect. TLS 1.3 is kept as well.
_ODOO_SSL_CIPHERS = (
    "ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:"
    "ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:"
    "DHE-RSA-AES128-GCM-SHA256:DHE-RSA-AES256-GCM-SHA384"
)
_GZIP = (
    "  gzip on;\n"
    "  gzip_types text/css text/scss text/plain text/xml application/xml application/json "
    "application/javascript;\n"
)


def _proxy_headers(extra: str = "") -> str:
    return (
        "    proxy_set_header X-Forwarded-Host $http_host;\n"
        "    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
        "    proxy_set_header X-Forwarded-Proto $scheme;\n"
        "    proxy_set_header X-Real-IP $remote_addr;\n"
        f"{extra}"
    )


def _secure_location_headers(nginx_version: tuple[int, int, int] | None) -> str:
    # add_header in a location replaces the server's, so each location carries it.
    lines = '    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains";\n'
    # proxy_cookie_flags appeared in nginx 1.19.3; an unknown version is taken as
    # older, since nginx -t rejects a directive it does not know.
    if nginx_version is not None and nginx_version >= (1, 19, 3):
        lines += "    proxy_cookie_flags session_id samesite=lax secure;\n"
    return lines


def _upstreams(config: InstanceConfig) -> str:
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
"""


def _locations(config: InstanceConfig, extra: str = "") -> str:
    return (
        f"  location {config.live_chat_location} {{\n"
        f"    proxy_pass http://odoochat_{config.instance};\n"
        "    proxy_set_header Upgrade $http_upgrade;\n"
        "    proxy_set_header Connection $connection_upgrade;\n"
        f"{_proxy_headers(extra)}"
        "  }\n\n"
        "  location / {\n"
        f"{_proxy_headers(extra)}"
        "    proxy_redirect off;\n"
        f"    proxy_pass http://odoo_{config.instance};\n"
        "  }\n"
    )


def _nginx_http_content(config: InstanceConfig) -> str:
    return f"""{_upstreams(config)}
server {{
  listen 80;
  server_name {config.domain};

  client_max_body_size 2048m;

  proxy_read_timeout 3600s;
  proxy_connect_timeout 720s;
  proxy_send_timeout 3600s;

  access_log {config.nginx_access_log};
  error_log  {config.nginx_error_log};

{_locations(config)}
{_GZIP}}}
"""


def _nginx_https_content(
    config: InstanceConfig, nginx_version: tuple[int, int, int] | None = None
) -> str:
    listen_block = _https_listen_block(nginx_version)
    return f"""{_upstreams(config)}
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
  ssl_session_timeout 30m;
  ssl_protocols TLSv1.2 TLSv1.3;
  ssl_ciphers {_ODOO_SSL_CIPHERS};
  ssl_prefer_server_ciphers off;

  proxy_read_timeout 3600s;
  proxy_connect_timeout 720s;
  proxy_send_timeout 3600s;

  access_log {config.nginx_access_log};
  error_log  {config.nginx_error_log};

{_locations(config, _secure_location_headers(nginx_version))}
{_GZIP}}}
"""


def _heredoc_delimiter(content: str) -> str:
    """A heredoc delimiter that cannot occur as a line of ``content``."""
    delimiter, n = "OIM_EOF", 0
    lines = set(content.splitlines())
    while delimiter in lines:
        n += 1
        delimiter = f"OIM_EOF_{n}"
    return delimiter


def staged_files_command(files: list[tuple[str, str, str]], validate: str) -> str:
    """Put ``(path, content, mode)`` files in place and keep them only if
    ``validate`` succeeds; otherwise every file is restored to what it was (or
    removed when it is new) and the command fails. A configuration a service would
    refuse at its next restart is never left enabled."""
    lines = ['backup=$(mktemp -d)', 'restore() {']
    for index, (path, _content, _mode) in enumerate(files):
        q = shlex.quote(path)
        lines.append(f'  if [ -e "$backup/{index}" ]; then cp -a "$backup/{index}" {q}; else rm -f {q}; fi')
    lines.append('}')
    for index, (path, content, mode) in enumerate(files):
        q = shlex.quote(path)
        delimiter = _heredoc_delimiter(content)
        lines += [
            f'if [ -e {q} ]; then cp -a {q} "$backup/{index}"; fi',
            f"cat > {shlex.quote(path + '.oim-new')} <<'{delimiter}'",
            content.rstrip("\n"),
            delimiter,
            f"chmod {mode} {shlex.quote(path + '.oim-new')}",
            f"mv -f {shlex.quote(path + '.oim-new')} {q}",
        ]
    lines += [
        f"if ! {{ {validate}; }}; then restore; rm -rf \"$backup\"; "
        "echo '[ERROR] Validation failed: the previous configuration was restored.' >&2; exit 1; fi",
        'rm -rf "$backup"',
    ]
    return "\n".join(lines)


def write_text_file_command(
    target_path: str, content: str, mode: str = "640", secrets: tuple[str, ...] = ()
) -> list[Command]:
    """Write ``content`` to ``target_path`` atomically with ``mode``: a private
    temporary file in the same directory, chmod, then rename — the file is never
    seen half-written or with the wrong mode. The content travels in the step's
    environment, so a file holding secrets (odoo.conf) is not in any process's
    arguments, and the preview shows it with ``secrets`` masked."""
    target = shlex.quote(target_path)
    command = (
        f'umask 077 && tmp=$(mktemp "$(dirname {target})/.oim-write.XXXXXX") && '
        f'printf \'%s\' "$OIM_FILE_CONTENT" > "$tmp" && chmod {mode} "$tmp" && mv -f "$tmp" {target}'
    )
    body = content if content.endswith("\n") else content + "\n"
    return [
        Command(
            description=tf('Write {} (mode {})', target_path, mode),
            command=command,
            env={"OIM_FILE_CONTENT": body},
            display=f"{command}\n--- {target_path} ---\n{mask(body, secrets)}",
        )
    ]


def _psql_stdin_command(psql: str, sql: str, secrets: tuple[str, ...], description: str) -> Command:
    """``sql`` fed to ``psql`` on stdin from the step's environment: a statement
    holding a password is in no process's arguments, and the preview masks it."""
    command = f'{psql} <<<"$OIM_SQL"'
    return Command(description, command, env={"OIM_SQL": sql}, display=f"{command}\n{mask(sql, secrets)}")


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
            "command -v logrotate >/dev/null 2>&1 || (apt-get update && DEBIAN_FRONTEND=noninteractive apt-get -y -o Dpkg::Options::=--force-confold -o DPkg::Lock::Timeout=600 install logrotate)",
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


# Odoo logs `Login failed for db:<db> login:<login> from <ip>` from 12.0 to 18.0
# and `Login failed for login:<login> from <ip>` from 19.0
# (odoo/addons/base/models/res_users.py), from the logger
# odoo.addons.base.models.res_users, followed by the request's perf info
# (odoo/netsvc.py format: `%(message)s %(perf_info)s`).
ODOO_LOGIN_FAILED_SAMPLES = (
    "2026-10-08 10:00:00,123 4321 INFO shop odoo.addons.base.models.res_users: "
    "Login failed for db:shop login:admin from 203.0.113.7 4 0.012 0.003",
    "2026-10-08 10:00:00,123 4321 INFO shop odoo.addons.base.models.res_users: "
    "Login failed for login:admin from 203.0.113.7 4 0.012 0.003",
)
# Ports a web ban covers: ufw's application profile installed by the nginx package.
# Without it, fail2ban's ufw action bans every port, SSH included.
UFW_WEB_APPLICATION = "Nginx Full"


def _fail2ban_base_content(
    ignore_ips: str,
    bantime: str,
    findtime: str,
    maxretry: int,
    recidive_bantime: str,
    nginx_logs: bool = True,
) -> str:
    """The base jails. sshd bans every port (it is SSH); the web jails ban only the
    web ports; recidive uses ufw too. The nginx jails are written only when nginx
    logs exist: fail2ban refuses to start with a jail whose log file is missing,
    and takes the sshd jail down with it."""
    web = f'ufw[application="{UFW_WEB_APPLICATION}"]'
    content = f"""[DEFAULT]
banaction = ufw
banaction_allports = ufw
backend = auto
ignoreip = {ignore_ips}
bantime = {bantime}
findtime = {findtime}
maxretry = {maxretry}

[sshd]
enabled = true
"""
    if nginx_logs:
        content += f"""
[nginx-http-auth]
enabled = true
banaction = {web}

[nginx-botsearch]
enabled = true
banaction = {web}
"""
    content += f"""
[recidive]
enabled = true
logpath = /var/log/fail2ban.log
bantime = {recidive_bantime}
findtime = 1d
maxretry = 5
"""
    return content


def _fail2ban_odoo_filter_content() -> str:
    return r"""[INCLUDES]
before = common.conf

[Definition]
# Odoo 12-18: "Login failed for db:<db> login:<login> from <ip>"; 19: no db part.
# The logger name anchors the line; the greedy login takes the last " from ",
# and only the request's perf numbers may follow the address.
failregex = ^\s*\d+ INFO \S+ odoo\.addons\.base\.models\.res_users: Login failed for (?:db:\S* )?login:.* from <HOST>(?: [\d.]+)*\s*$

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
banaction = ufw[application="{UFW_WEB_APPLICATION}"]
bantime = {bantime}
findtime = {findtime}
maxretry = {maxretry}
"""


_FAIL2BAN_INSTALL = (
    "command -v fail2ban-client >/dev/null 2>&1 || (apt-get update && DEBIAN_FRONTEND=noninteractive "
    "apt-get -y -o Dpkg::Options::=--force-confold -o DPkg::Lock::Timeout=600 install fail2ban)"
)
_FAIL2BAN_WAIT = (
    "for _ in $(seq 1 15); do fail2ban-client ping >/dev/null 2>&1 && exit 0; sleep 1; done; "
    "echo '[ERROR] fail2ban is active but its socket is unavailable after waiting.'; "
    "systemctl status fail2ban --no-pager -n 50 || true; exit 1"
)
_FAIL2BAN_FILTER = "/etc/fail2ban/filter.d/odoo-auth.conf"


def _fail2ban_apply_commands() -> list[Command]:
    return [
        Command('Enable and start fail2ban', "systemctl enable --now fail2ban"),
        Command('Reload fail2ban', "fail2ban-client reload"),
        Command('Wait for the fail2ban socket to be ready', _FAIL2BAN_WAIT),
    ]


def _filter_self_test() -> Command:
    """The filter must match Odoo's own login-failure line of every version; an
    empty production log proves nothing (fail2ban-regex exits 0 with 0 matches)."""
    checks = " && ".join(
        f"fail2ban-regex {shlex.quote(sample)} {shlex.quote(_FAIL2BAN_FILTER)} | grep -q '1 matched'"
        for sample in ODOO_LOGIN_FAILED_SAMPLES
    )
    return Command(
        'Test the Odoo filter against the login-failure line of Odoo 12-18 and 19',
        f"{checks} || {{ echo '[ERROR] The odoo-auth filter does not match Odoo login failures.' >&2; exit 1; }}",
    )


def plan_fail2ban_base_setup(
    ignore_ips: str,
    bantime: str = "1h",
    findtime: str = "10m",
    maxretry: int = 8,
    recidive_bantime: str = "24h",
    nginx_logs: bool = True,
) -> list[Command]:
    jail_base_path = "/etc/fail2ban/jail.d/odoo-instance-manager.local"
    content = _fail2ban_base_content(ignore_ips, bantime, findtime, maxretry, recidive_bantime, nginx_logs)
    return [
        Command('Ensure fail2ban is installed', _FAIL2BAN_INSTALL),
        Command('Create /etc/fail2ban/jail.d', "mkdir -p /etc/fail2ban/jail.d"),
        Command(
            tf('Write {} and keep it only if fail2ban accepts it', jail_base_path),
            staged_files_command([(jail_base_path, content, "644")], "fail2ban-client -t"),
        ),
        *_fail2ban_apply_commands(),
    ]


def plan_fail2ban_enable_odoo_instance(
    instance: str,
    log_path: str,
    bantime: str = "1h",
    findtime: str = "10m",
    maxretry: int = 8,
) -> list[Command]:
    jail_name = f"odoo-auth-{_safe_token(instance)}"
    jail_path = f"/etc/fail2ban/jail.d/{jail_name}.local"
    files = [
        (_FAIL2BAN_FILTER, _fail2ban_odoo_filter_content(), "644"),
        (jail_path, _fail2ban_odoo_jail_content(jail_name, log_path, bantime, findtime, maxretry), "644"),
    ]
    return [
        Command('Ensure fail2ban is installed', _FAIL2BAN_INSTALL),
        Command('Create fail2ban directories', "mkdir -p /etc/fail2ban/filter.d /etc/fail2ban/jail.d"),
        Command('Validate instance log', f"test -f {shlex.quote(log_path)}"),
        Command(
            tf('Write the odoo-auth filter and the {} jail; keep them only if fail2ban accepts them', jail_name),
            staged_files_command(files, "fail2ban-client -t"),
        ),
        _filter_self_test(),
        *_fail2ban_apply_commands(),
    ]


def plan_fail2ban_ensure_odoo_filter() -> list[Command]:
    return [
        Command('Create fail2ban filters directory', "mkdir -p /etc/fail2ban/filter.d"),
        Command(
            'Write the odoo-auth filter and keep it only if fail2ban accepts it',
            staged_files_command([(_FAIL2BAN_FILTER, _fail2ban_odoo_filter_content(), "644")],
                                 "fail2ban-client -t"),
        ),
        _filter_self_test(),
    ]


def plan_odoo_log_dir(config: InstanceConfig) -> list[Command]:
    """The shared ``/var/log/odoo`` belongs to root (755) and each instance owns only
    its own log (640): every instance writes its log, none can touch another's, and
    logrotate (as root) rotates them with no ``su``.

    Earlier installs gave the whole directory to the newest instance; the logs of
    the other tool-made instances (user home ``/opt/odoo/<name>``) get their owner
    back, and their logrotate policies lose the ``su`` that root rotation no longer
    needs."""
    log = shlex.quote(config.odoo_log_file)
    owner = f"{shlex.quote(config.odoo_user)}:{shlex.quote(config.odoo_user)}"
    return [
        Command(
            'Make /var/log/odoo root-owned (755)',
            "install -d -m 755 /var/log/odoo && chown root:root /var/log/odoo && chmod 755 /var/log/odoo",
        ),
        Command(
            tf('Give each instance its own log back ({} included)', config.odoo_log_file),
            f"touch {log} && chown {owner} {log} && chmod 640 {log} && "
            "for f in /var/log/odoo/*.log; do [ -f \"$f\" ] || continue; "
            'u=$(basename "$f" .log); '
            '[ "$(getent passwd "$u" | cut -d: -f6)" = "/opt/odoo/$u" ] && chown "$u:$u" "$f"; '
            "done; true",
        ),
        Command(
            'Drop su from the Odoo logrotate policies (root rotates them)',
            "for f in /etc/logrotate.d/odoo-*; do [ -f \"$f\" ] || continue; "
            "grep -q '^/var/log/odoo/' \"$f\" || continue; "
            "sed -i '/^[[:space:]]*su [a-z_][a-z0-9_]* [a-z_][a-z0-9_]*$/d' \"$f\"; done; true",
        ),
    ]


def plan_odoo_base_setup(
    config: InstanceConfig, service_autostart: bool = True, start_now: bool = True
) -> list[Command]:
    config.normalize_defaults()
    config.ensure_strong_secrets()
    config.validate_identifiers()
    commands: list[Command] = [
        Command('Update packages', "apt-get update"),
        Command(
            'Install Odoo base dependencies',
            "DEBIAN_FRONTEND=noninteractive apt-get -y -o Dpkg::Options::=--force-confold -o DPkg::Lock::Timeout=600 install git build-essential pkg-config python3 python3-venv python3-dev python3-pip "
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
            f"mkdir -p '{config.odoo_home}/odoo' '{config.odoo_home}/addons-oca' '{config.odoo_home}/addons-custom' '{config.odoo_conf_dir}'",
        ),
        Command(
            'Adjust base ownership',
            f"chown -R '{config.odoo_user}:{config.odoo_user}' '{config.odoo_home}'",
        ),
        *plan_odoo_log_dir(config),
        Command('Permissions on config folder', f"chmod 750 '{config.odoo_conf_dir}'"),
    ]
    if config.data_dir:
        commands.append(
            Command(
                tf('Create the data dir {} (filestores, sessions)', config.data_dir),
                f"install -d -m 750 -o {shlex.quote(config.odoo_user)} -g {shlex.quote(config.odoo_user)} "
                f"{shlex.quote(config.data_dir)}",
            )
        )
    commands += [
        Command(
            tf('Clone {} {} if missing', support.CORE_LABELS[config.core], config.repo_branch),
            _as_instance_user(
                config,
                f"test -d {shlex.quote(config.odoo_home + '/odoo/.git')} || git clone --depth 1 "
                f"--branch {shlex.quote(config.repo_branch)} {shlex.quote(support.CORE_URLS[config.core])} "
                f"{shlex.quote(config.odoo_home + '/odoo')}",
            ),
        ),
        *_venv_commands(config),
    ]

    commands.extend(
        write_text_file_command(
            config.odoo_conf_file, _odoo_conf_content(config), "640",
            secrets=(config.odoo_admin_passwd, config.db_password),
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
                'Enable Odoo service autostart',
                f"systemctl enable '{config.odoo_service}'",
            )
        )
    else:
        commands.append(
            Command(
                'Disable Odoo service autostart',
                f"systemctl disable '{config.odoo_service}' || true",
            )
        )
    # Duplication provisions the target before its database exists; it starts the
    # service itself after seeding, so it passes start_now=False.
    if start_now:
        commands.append(
            Command(
                'Start the Odoo service',
                f"systemctl start '{config.odoo_service}'",
            )
        )
    return commands


def _local_psql(config: InstanceConfig) -> str:
    """psql as postgres on the local server, at the instance's port (a host may run
    a second cluster)."""
    return f"sudo -u postgres psql -X -p {int(config.db_port)}"


def _pg_hba_append_command(config: InstanceConfig) -> str:
    """Append the app server's rule to pg_hba.conf unless the same line is there.
    The values are validated (role, IP) and the line is shell-quoted as one word."""
    rule = f"host    all     {config.db_user}     {host_cidr(config.app_server_ip)}     scram-sha-256"
    return (
        f'PG_HBA=$({_local_psql(config)} -t -P format=unaligned -c "SHOW hba_file;") && '
        f'{{ grep -qxF -- {shlex.quote(rule)} "$PG_HBA" || printf \'%s\\n\' {shlex.quote(rule)} >> "$PG_HBA"; }}'
    )


def _as_instance_user(config: InstanceConfig, script: str) -> str:
    """``script`` run by bash as the instance user, passed as one quoted word."""
    return f"sudo -u {shlex.quote(config.odoo_user)} -H bash -c {shlex.quote(script)}"


def _requirements_install(pip: str, requirements: str, major: int) -> str:
    """``pip install -r`` of the branch's requirements, with any substitute applied:
    the dropped project's line is filtered out and its replacement installed in the
    same resolution (see ``support.REQUIREMENT_SUBSTITUTES``)."""
    substitute = support.REQUIREMENT_SUBSTITUTES.get(major)
    if substitute is None:
        return f"{shlex.quote(pip)} install -r {shlex.quote(requirements)}"
    dropped, replacement = substitute
    pattern = shlex.quote(f"^{dropped}([=<>!~; ]|$)")
    return (
        f"set -o pipefail && grep -v -i -E {pattern} {shlex.quote(requirements)} | "
        f"{shlex.quote(pip)} install -r /dev/stdin {shlex.quote(replacement)}"
    )


def _venv_commands(config: InstanceConfig) -> list[Command]:
    """Build the venv with the interpreter chosen for the version, then install
    pip/wheel, the setuptools the version needs, and its requirements."""
    venv = f"{config.odoo_home}/venv"
    if config.python_source == support.UV:
        create = (
            f"env UV_PYTHON_INSTALL_DIR={shlex.quote(support.UV_PYTHON_DIR)} UV_PYTHON_DOWNLOADS=never "
            "UV_PYTHON_PREFERENCE=only-managed "
            f"{support.UV_BIN} venv --seed --allow-existing --no-project --python {shlex.quote(config.python)} "
            f"{shlex.quote(venv)}"
        )
        label = tf('Create the venv with Python {} (uv)', config.python)
    else:
        create = f"python3 -m venv {shlex.quote(venv)}"
        label = 'Create the venv with the host python3'
    pip = f"{venv}/bin/pip"
    major = config.odoo_major
    return [
        Command(label, _as_instance_user(config, create)),
        Command(
            tf('Install pip, wheel and {} in the venv', support.setuptools_requirement(major)),
            _as_instance_user(
                config,
                f"{shlex.quote(pip)} install --upgrade pip wheel "
                f"{shlex.quote(support.setuptools_requirement(major))}",
            ),
        ),
        Command(
            tf('Install the Odoo {} requirements', config.repo_branch),
            _as_instance_user(
                config, _requirements_install(pip, f"{config.odoo_home}/odoo/requirements.txt", major)
            ),
        ),
    ]


def plan_ensure_uv(arch: str) -> list[Command]:
    """Install the pinned uv into /usr/local/bin unless that exact version is there,
    from GitHub's release asset, checked against its published SHA-256 before
    anything runs. Another uv on root's PATH does not count."""
    asset = support.UV_ASSETS.get(arch)
    if asset is None:
        return []
    filename, sha256 = asset
    url = f"https://github.com/astral-sh/uv/releases/download/{support.UV_VERSION}/{filename}"
    stem = filename.removesuffix(".tar.gz")
    script = (
        f'[ "$({support.UV_BIN} --version 2>/dev/null | cut -d" " -f2)" = {shlex.quote(support.UV_VERSION)} ] && exit 0; '

        'tmp=$(mktemp -d) && trap \'rm -rf "$tmp"\' EXIT && '
        f'curl -fsSL -o "$tmp/{filename}" {shlex.quote(url)} && '
        f'echo {shlex.quote(sha256 + "  ")}"$tmp/{filename}" | sha256sum -c - && '
        f'tar -xzf "$tmp/{filename}" -C "$tmp" && '
        f'install -m 755 "$tmp/{stem}/uv" "$tmp/{stem}/uvx" /usr/local/bin/'
    )
    return [
        Command(
            'Ensure curl is available',
            "command -v curl >/dev/null 2>&1 || (apt-get update && DEBIAN_FRONTEND=noninteractive apt-get -y -o Dpkg::Options::=--force-confold -o DPkg::Lock::Timeout=600 install curl)",
        ),
        Command(tf('Install uv {} (checksum-verified) unless it is there', support.UV_VERSION), script),
    ]


def plan_uv_python(python: str) -> list[Command]:
    """Install a uv-managed CPython into the shared, root-owned interpreter dir,
    readable (not writable) by every instance user."""
    directory = shlex.quote(support.UV_PYTHON_DIR)
    return [
        Command(
            tf('Install Python {} with uv into {}', python, support.UV_PYTHON_DIR),
            f"install -d -m 755 {directory} && "
            # --no-bin: no `python3.x` link in root's PATH; venvs name the interpreter.
            f"UV_PYTHON_INSTALL_DIR={directory} {support.UV_BIN} python install --no-bin {shlex.quote(python)} && "
            f"chmod -R a+rX,go-w {directory}",
        )
    ]


def _postgres_floor_commands(config: InstanceConfig) -> list[Command]:
    """Refuse a local server older than the Odoo version's documented floor."""
    version = support.version_support(config.version)
    if version is None or version.postgres_min is None:
        return []
    floor = version.postgres_min
    return [
        Command(
            tf('Check PostgreSQL is {} or newer (Odoo {} requirement)', floor, version.major),
            f"v=$({_local_psql(config)} -tAc 'SHOW server_version_num') && "
            f'[ "$v" -ge {floor * 10000} ] || '
            f"{{ echo \"PostgreSQL $v is older than {floor}, the floor of Odoo {version.major}.\" >&2; exit 1; }}",
        )
    ]


def plan_db_setup(
    config: InstanceConfig, ensure_remote_access: bool = True, reset_password: bool = False
) -> list[Command]:
    config.normalize_defaults()
    config.ensure_strong_secrets()
    config.validate_identifiers()
    role_sql = _db_role_create_if_missing_sql(config, reset_password)

    commands: list[Command] = [
        Command(
            'Install PostgreSQL', "apt-get update && DEBIAN_FRONTEND=noninteractive apt-get -y -o Dpkg::Options::=--force-confold -o DPkg::Lock::Timeout=600 install postgresql"
        ),
        Command('Enable and start PostgreSQL', "systemctl enable --now postgresql"),
        *_postgres_floor_commands(config),
        _psql_stdin_command(
            f"{_local_psql(config)} -v ON_ERROR_STOP=1", role_sql, (config.db_password,),
            'Ensure PostgreSQL role (create if missing)',
        ),
        _db_connectivity_check(config),
    ]

    if ensure_remote_access:
        commands.extend(
            [
                # ALTER SYSTEM wins over postgresql.conf and conf.d; listen_addresses
                # needs a restart, which drops every instance's connections, so only
                # when the value changes. The result is read back.
                Command(
                    "Listen on every address (listen_addresses = '*')",
                    f"psql=({_local_psql(config)} -tA -v ON_ERROR_STOP=1); "
                    'if [ "$("${psql[@]}" -c "SHOW listen_addresses")" != "*" ]; then '
                    '"${psql[@]}" -c "ALTER SYSTEM SET listen_addresses = \'*\'" && systemctl restart postgresql; fi && '
                    '[ "$("${psql[@]}" -c "SHOW listen_addresses")" = "*" ]',
                ),
                Command(
                    'Add pg_hba rule for the app-server IP',
                    _pg_hba_append_command(config),
                ),
                Command('Reload PostgreSQL (pg_hba)', "systemctl reload postgresql"),
            ]
        )

    return commands


def plan_ensure_db_role(config: InstanceConfig, reset_password: bool = False) -> list[Command]:
    config.normalize_defaults()
    config.ensure_strong_secrets()
    config.validate_identifiers()

    commands: list[Command] = []
    if _is_local_db_host(config.db_host):
        role_sql = _db_role_create_if_missing_sql(config, reset_password)
        commands.append(
            _psql_stdin_command(
                f"{_local_psql(config)} -v ON_ERROR_STOP=1", role_sql, (config.db_password,),
                'Ensure local PostgreSQL role (create if missing)',
            )
        )
    else:
        commands.append(
            Command(
                'Remote DB role info',
                "echo '[INFO] Remote DB host: role creation is skipped without remote admin credentials; the given user login will be validated.'",
            )
        )

    commands.append(_db_connectivity_check(config))
    return commands


def _nginx_switch_command(available: str, content: str, enable: str, disable: str) -> str:
    """Write the vhost, enable it and disable its sibling, then keep the change only
    if ``nginx -t`` accepts the whole configuration; otherwise the vhost file and
    both links are put back as they were. A broken vhost left enabled would stop
    nginx — every instance on the host — at its next restart."""
    q = shlex.quote
    delimiter = _heredoc_delimiter(content)
    return "\n".join([
        "backup=$(mktemp -d)",
        f'if [ -e {q(available)} ]; then cp -a {q(available)} "$backup/available"; fi',
        f'if [ -L {q(enable)} ]; then cp -a {q(enable)} "$backup/enable"; fi',
        f'if [ -L {q(disable)} ]; then cp -a {q(disable)} "$backup/disable"; fi',
        "restore() {",
        f'  if [ -e "$backup/available" ]; then cp -a "$backup/available" {q(available)}; else rm -f {q(available)}; fi',
        f'  rm -f {q(enable)} {q(disable)}',
        f'  if [ -L "$backup/enable" ]; then cp -a "$backup/enable" {q(enable)}; fi',
        f'  if [ -L "$backup/disable" ]; then cp -a "$backup/disable" {q(disable)}; fi',
        "}",
        f"cat > {q(available)} <<'{delimiter}'",
        content.rstrip("\n"),
        delimiter,
        f"chmod 644 {q(available)}",
        f"rm -f {q(disable)}",
        f"ln -sf {q(available)} {q(enable)}",
        'if ! nginx -t; then restore; rm -rf "$backup"; '
        "echo '[ERROR] nginx refused the configuration: the previous one was restored.' >&2; exit 1; fi",
        'rm -rf "$backup"',
    ])


def plan_nginx_http(
    config: InstanceConfig, nginx_version: tuple[int, int, int] | None = None
) -> list[Command]:
    # nginx_version is accepted for signature parity with plan_nginx_https; the
    # plain HTTP vhost listens on port 80 only and needs no http2 adaptation.
    site_available = f"/etc/nginx/sites-available/{config.nginx_http_name}"
    return [
        Command('Install Nginx', "command -v nginx >/dev/null 2>&1 || (apt-get update && DEBIAN_FRONTEND=noninteractive apt-get -y -o Dpkg::Options::=--force-confold -o DPkg::Lock::Timeout=600 install nginx)"),
        Command('Enable Nginx', "systemctl enable --now nginx"),
        Command(
            'Enable the instance HTTP vhost (kept only if nginx -t accepts it)',
            _nginx_switch_command(
                site_available, _nginx_http_content(config),
                f"/etc/nginx/sites-enabled/{config.nginx_http_name}",
                f"/etc/nginx/sites-enabled/{config.nginx_https_name}",
            ),
        ),
        Command('Reload Nginx', "systemctl reload nginx"),
    ]


def plan_nginx_https(
    config: InstanceConfig, nginx_version: tuple[int, int, int] | None = None
) -> list[Command]:
    site_available = f"/etc/nginx/sites-available/{config.nginx_https_name}"
    return [
        Command('Install Nginx', "command -v nginx >/dev/null 2>&1 || (apt-get update && DEBIAN_FRONTEND=noninteractive apt-get -y -o Dpkg::Options::=--force-confold -o DPkg::Lock::Timeout=600 install nginx)"),
        Command('Enable Nginx', "systemctl enable --now nginx"),
        Command(
            'Enable the instance HTTPS vhost (kept only if nginx -t accepts it)',
            _nginx_switch_command(
                site_available, _nginx_https_content(config, nginx_version),
                f"/etc/nginx/sites-enabled/{config.nginx_https_name}",
                f"/etc/nginx/sites-enabled/{config.nginx_http_name}",
            ),
        ),
        Command('Reload Nginx', "systemctl reload nginx"),
    ]


_PEM_CERTS_AWK = (
    "awk 'BEGIN{c=0} /-----BEGIN CERTIFICATE-----/{c=1} c{gsub(/\\r$/,\"\"); print} "
    "/-----END CERTIFICATE-----/{c=0; print \"\"}'"
)


def plan_copy_custom_certs(
    config: InstanceConfig,
    cert_src: str,
    key_src: str,
    intermediate_src: str | None,
) -> list[Command]:
    """Install the operator's certificate, key and optional chain in one step.

    They are copied into a staging directory beside the live files and checked there
    — the key, the certificate, that they match, the full chain — and only then
    moved into place, the previous files kept as ``.previous``. A wrong file never
    replaces a working one: the next nginx restart, of any instance, would fail."""
    q = shlex.quote
    ssl_dir = q(config.nginx_ssl_dir)
    targets = [("crt", config.ssl_cert_file, "644"), ("key", config.ssl_key_file, "640"),
               ("fullchain", config.ssl_fullchain_file, "644")]
    lines = [
        "set -e",
        f"install -d -m 750 -o root -g www-data {ssl_dir}",
        f'stage=$(mktemp -d {q(config.nginx_ssl_dir + "/.stage.XXXXXX")})',
        'trap \'rm -rf "$stage"\' EXIT',
        f'cp -- {q(cert_src)} "$stage/crt"',
        f'cp -- {q(key_src)} "$stage/key"',
    ]
    if intermediate_src:
        targets.append(("intermediate", config.ssl_intermediate_file, "644"))
        lines += [
            f'cp -- {q(intermediate_src)} "$stage/intermediate"',
            f'{{ {_PEM_CERTS_AWK} "$stage/crt"; {_PEM_CERTS_AWK} "$stage/intermediate"; }} > "$stage/fullchain"',
        ]
    else:
        lines.append('cp "$stage/crt" "$stage/fullchain"')
    lines += [
        'openssl pkey -in "$stage/key" -noout',
        'openssl x509 -in "$stage/crt" -noout',
        'cert_fp=$(openssl x509 -in "$stage/crt" -pubkey -noout | openssl pkey -pubin -outform PEM | sha256sum)',
        'key_fp=$(openssl pkey -in "$stage/key" -pubout -outform PEM | sha256sum)',
        'if [ "$cert_fp" != "$key_fp" ]; then '
        "echo '[ERROR] The private key does not match the selected public certificate.' >&2; exit 1; fi",
        'openssl x509 -in "$stage/fullchain" -noout',
    ]
    for name, target, mode in targets:
        lines += [
            f'chown root:www-data "$stage/{name}" && chmod {mode} "$stage/{name}"',
            f"if [ -e {q(target)} ]; then cp -a {q(target)} {q(target + '.previous')}; fi",
        ]
    lines += [f'mv -f "$stage/{name}" {q(target)}' for name, target, _mode in targets]
    return [
        Command(
            'Install the certificate files, kept only if the key and chain check out',
            "\n".join(lines),
        )
    ]


def plan_ensure_self_signed_certs(config: InstanceConfig) -> list[Command]:
    q = shlex.quote
    key, cert, chain = q(config.ssl_key_file), q(config.ssl_cert_file), q(config.ssl_fullchain_file)
    return [
        Command(
            'Ensure dedicated SSL directory',
            f"install -d -m 750 -o root -g www-data {q(config.nginx_ssl_dir)}",
        ),
        Command(
            'Generate self-signed if missing (server.key/fullchain)',
            f"if [ -s {key} ] && [ -s {chain} ]; then "
            "echo '[INFO] Existing self-signed certificate, reusing it.'; "
            "else "
            "command -v openssl >/dev/null 2>&1 || (apt-get update && DEBIAN_FRONTEND=noninteractive apt-get -y -o Dpkg::Options::=--force-confold -o DPkg::Lock::Timeout=600 install openssl); "
            "openssl req -x509 -nodes -newkey rsa:2048 -sha256 -days 825 "
            f"-keyout {key} -out {cert} -subj {q('/CN=' + config.domain)} && "
            f"cp {cert} {chain}; "
            "fi",
        ),
        Command(
            'Adjust self-signed certificate permissions',
            f"chown root:www-data {key} {cert} {chain} && chmod 640 {key} && chmod 644 {cert} {chain}",
        ),
    ]


_TIMESTAMP_GLOB = "[0-9]" * 8 + "_" + "[0-9]" * 6
BACKUP_DUMP_SUFFIX = ".dump"
BACKUP_FILESTORE_SUFFIX = ".filestore.tar.gz"


def backup_prefix(instance: str, db_name: str) -> str:
    """The name every backup of ``db_name`` for ``instance`` starts with.

    Both halves are in the name so retention keeps N backups of one database:
    keyed on the instance alone, instance ``shop`` pruned ``shop_eu``'s dumps and a
    test database's backups pushed production's out of the window."""
    return f"{instance}--{db_name}--"


def backup_basename(instance: str, db_name: str, timestamp: str) -> str:
    return f"{backup_prefix(instance, db_name)}{timestamp}"


def _prune_command(dir_word: str, glob_word: str, keep: int) -> str:
    """Delete the files in a directory matching a glob beyond the ``keep`` newest.

    Both arguments are shell words the caller has already quoted (a literal path, or
    a quoted ``"$VAR"`` in a script). ``find`` exits 0 when nothing matches, so the
    command is safe under ``set -euo pipefail``; the glob is exact (prefix +
    timestamp + suffix), so it never reaches another instance's or database's files.
    The newest are the latest *names*: the timestamp in the name is when the backup
    was taken, while a copied or restored file's mtime is not."""
    return (
        f"find {dir_word} -maxdepth 1 -type f -name {glob_word} "
        "-printf '%p\\n' | sort -r | tail -n +" + str(int(keep) + 1) + " "
        "| xargs -r -d '\\n' rm -f --"
    )


def plan_backup_retention(
    config: InstanceConfig, backup_dir: str, keep: int, db_names: list[str]
) -> list[Command]:
    """Delete an instance's oldest backups, keeping the ``keep`` newest of each kind
    (DB dumps and filestore archives) **per database**. Backups written before the
    names carried the database (``<instance>_<timestamp>``) are pruned as one more
    group, matched exactly."""
    commands: list[Command] = []
    groups = [(backup_prefix(config.instance, db), db) for db in db_names]
    groups.append((f"{config.instance}_", tf("{} (old names)", config.instance)))
    for prefix, label in groups:
        for suffix, kind in (
            (BACKUP_DUMP_SUFFIX, 'DB dumps'),
            (BACKUP_FILESTORE_SUFFIX, 'filestore archives'),
        ):
            commands.append(
                Command(
                    tf('Delete old {} of {} (keep the {} most recent)', kind, label, keep),
                    _prune_command(
                        shlex.quote(backup_dir),
                        shlex.quote(f"{prefix}{_TIMESTAMP_GLOB}{suffix}"),
                        keep,
                    ),
                )
            )
    return commands


def _script_glob(suffix: str) -> str:
    """The backup-name glob as a script word: ``$PREFIX`` expanded, the rest literal."""
    return '"$PREFIX"' + shlex.quote(_TIMESTAMP_GLOB + suffix)


def _scheduled_backup_script(
    config: InstanceConfig,
    db_name: str,
    backup_dir: str,
    filestore_dir: str,
    keep: int,
    include_filestore: bool,
) -> str:
    """The script the timer runs. Every value is shell-quoted, files are private
    (``umask 077``), a partial file never survives (trap), and the script exits
    non-zero whenever the dump, its check or the archive failed — so the unit shows
    failed instead of reporting a backup that is not there."""
    prefix = backup_prefix(config.instance, db_name)
    lines = [
        "#!/usr/bin/env bash",
        "# Generated by odoo-instance-manager — scheduled backup.",
        "set -euo pipefail",
        "umask 077",
        f"BACKUP_DIR={shlex.quote(backup_dir)}",
        f"DB={shlex.quote(db_name)}",
        f"PREFIX={shlex.quote(prefix)}",
        "TS=$(date +%Y%m%d_%H%M%S)",
        'PARTIAL=""',
        'cleanup() { if [ -n "$PARTIAL" ]; then rm -f -- "$PARTIAL"; fi; }',
        "trap cleanup EXIT",
        'install -d -m 700 "$BACKUP_DIR"',
        'chmod 700 "$BACKUP_DIR"',
        'PARTIAL="$BACKUP_DIR/$PREFIX$TS.dump.partial"',
        # root writes the file, into its own private directory; postgres only reads.
        "# shellcheck disable=SC2024",
        'sudo -u postgres pg_dump -Fc -- "$DB" > "$PARTIAL"',
        # A truncated or empty dump has no readable table of contents.
        'pg_restore --list "$PARTIAL" > /dev/null',
        f'mv -- "$PARTIAL" "$BACKUP_DIR/$PREFIX$TS{BACKUP_DUMP_SUFFIX}"',
        'PARTIAL=""',
        _prune_command('"$BACKUP_DIR"', _script_glob(BACKUP_DUMP_SUFFIX), keep),
    ]
    if include_filestore:
        lines += [
            f"FILESTORE={shlex.quote(filestore_dir)}",
            'if [ ! -d "$FILESTORE" ]; then echo "Filestore not found: $FILESTORE" >&2; exit 1; fi',
            'PARTIAL="$BACKUP_DIR/$PREFIX$TS.filestore.tar.gz.partial"',
            # Exit 1 is GNU tar's "a file changed while read": Odoo keeps writing
            # attachments, and every file already archived is complete. tar reads as
            # the instance user (a link it planted reaches nothing root alone could
            # read); root writes the archive.
            f"rc=0; sudo -u {shlex.quote(config.odoo_user)} -H "
            'tar --warning=no-file-changed -czf - -C "$FILESTORE" . > "$PARTIAL" || rc=$?',
            'if [ "$rc" -gt 1 ]; then exit "$rc"; fi',
            f'mv -- "$PARTIAL" "$BACKUP_DIR/$PREFIX$TS{BACKUP_FILESTORE_SUFFIX}"',
            'PARTIAL=""',
            _prune_command('"$BACKUP_DIR"', _script_glob(BACKUP_FILESTORE_SUFFIX), keep),
        ]
    return "\n".join(lines) + "\n"


def _scheduled_backup_service(name: str, script_path: str, instance: str) -> str:
    return f'''[Unit]
Description=Scheduled Odoo backup ({instance})
After=postgresql.service

[Service]
Type=oneshot
UMask=0077
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
            "command -v ufw >/dev/null 2>&1 || (apt-get update && DEBIAN_FRONTEND=noninteractive apt-get -y -o Dpkg::Options::=--force-confold -o DPkg::Lock::Timeout=600 install ufw)",
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


def plan_ufw_delete_rule(number: int, expected_line: str) -> list[Command]:
    """Delete rule ``number`` only if it is still the rule the operator saw. fail2ban
    prepends its bans to the list, so the numbers shift while the operator reads:
    without the check, "delete #5" can delete the SSH allow that moved to #5."""
    return [
        Command(
            tf('Delete UFW rule #{}', int(number)),
            f"ufw status numbered | grep -qxF -- {shlex.quote(expected_line)} || "
            "{ echo '[ERROR] The rule list changed since it was shown; nothing was deleted.' >&2; exit 1; } && "
            f"ufw --force delete {int(number)}",
        )
    ]


_WKHTMLTOPDF_BASE_URL = (
    "https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6.1-3"
)
# (OS codename, machine) -> (asset filename, sha256), Qt-patched 0.12.6.1-3. The
# jammy amd64 build is verified against Odoo's own pinned checksum (its SHA-1
# 967390a759707337b46d1c02452e2bb6b2dc6d59 matches the Odoo 18 Dockerfile) and also
# runs on noble (24.04); the other checksums were computed from the release's
# assets (GitHub publishes no digest for this release). Pairs without a compatible
# asset — Debian 13, Ubuntu 26.04, other machines — resolve to None, so the caller
# offers the distribution package or skip, never a guessed URL.
_WKHTMLTOPDF_ASSETS: dict[tuple[str, str], tuple[str, str]] = {
    ("jammy", "x86_64"): ("wkhtmltox_0.12.6.1-3.jammy_amd64.deb",
                          "4f723b2691ad8638a9df960e0421d346d7315083e3583a334f33362280ddba15"),
    ("jammy", "aarch64"): ("wkhtmltox_0.12.6.1-3.jammy_arm64.deb",
                           "2095f20256661ebf0983b9311168596c9d012666e21a94bc24f304db6ac69ec5"),
    ("bookworm", "x86_64"): ("wkhtmltox_0.12.6.1-3.bookworm_amd64.deb",
                             "98ba0d157b50d36f23bd0dedf4c0aa28c7b0c50fcdcdc54aa5b6bbba81a3941d"),
    ("bookworm", "aarch64"): ("wkhtmltox_0.12.6.1-3.bookworm_arm64.deb",
                              "b6606157b27c13e044d0abbe670301f88de4e1782afca4f9c06a5817f3e03a9c"),
    ("bullseye", "x86_64"): ("wkhtmltox_0.12.6.1-3.bullseye_amd64.deb",
                             "9c687f0c58cf50e01f2a6375d2e34372f8feeec56a84690ea113d298fccadd98"),
    ("bullseye", "aarch64"): ("wkhtmltox_0.12.6.1-3.bullseye_arm64.deb",
                              "e73435a82cf21ba0387bfee32a193f221fa43e48dda6ed38b12e4c1b70c69728"),
}
# Ubuntu 24.04 runs the 22.04 build.
_WKHTMLTOPDF_SAME_AS = {"noble": "jammy"}


def resolve_wkhtmltopdf_asset(codename: str, arch: str = "x86_64") -> tuple[str, str, str] | None:
    """``(url, filename, sha256)`` for the patched wkhtmltopdf matching ``codename``
    and the machine ``arch`` (``x86_64``, ``aarch64``), or ``None`` when no compatible
    verified asset is pinned (the caller then offers the distro package or skip; it
    never guesses a URL)."""
    name = (codename or "").strip().lower()
    entry = _WKHTMLTOPDF_ASSETS.get((_WKHTMLTOPDF_SAME_AS.get(name, name), arch))
    if not entry:
        return None
    filename, sha256 = entry
    return f"{_WKHTMLTOPDF_BASE_URL}/{filename}", filename, sha256


def plan_install_wkhtmltopdf(mode: str, codename: str = "", arch: str = "x86_64") -> list[Command]:
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
                "apt-get update && DEBIAN_FRONTEND=noninteractive apt-get -y -o Dpkg::Options::=--force-confold -o DPkg::Lock::Timeout=600 install wkhtmltopdf",
            )
        ]
    if mode != "patched":
        return []
    asset = resolve_wkhtmltopdf_asset(codename, arch)
    if asset is None:
        return []
    url, filename, sha256 = asset
    # One step in a private temporary directory: a fixed /tmp name could be planted,
    # or swapped between the check and the install.
    deb = f'"$tmp"/{shlex.quote(filename)}'
    return [
        Command(
            'Ensure curl is available',
            "command -v curl >/dev/null 2>&1 || (apt-get update && DEBIAN_FRONTEND=noninteractive apt-get -y -o Dpkg::Options::=--force-confold -o DPkg::Lock::Timeout=600 install curl)",
        ),
        Command(
            tf('Download, verify (SHA-256) and install patched wkhtmltopdf ({})', filename),
            "tmp=$(mktemp -d) && trap 'rm -rf \"$tmp\"' EXIT && "
            f"curl -fSL -o {deb} {shlex.quote(url)} && "
            f'echo {shlex.quote(sha256)}"  "{deb} | sha256sum -c - && '
            # apt reads local packages as _apt: the verified file is made readable.
            f'chmod 755 "$tmp" && chmod 644 {deb} && '
            "apt-get update && DEBIAN_FRONTEND=noninteractive apt-get -y -o Dpkg::Options::=--force-confold "
            f"-o DPkg::Lock::Timeout=600 install {deb}",
        ),
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
