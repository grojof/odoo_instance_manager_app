from __future__ import annotations

import ipaddress
import re
import secrets
from dataclasses import dataclass
from typing import ClassVar

INSTANCE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
POSTGRES_IDENTIFIER_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
# A database name as Odoo's own database manager accepts it (DBNAME_PATTERN in
# odoo/service/db.py), capped at PostgreSQL's 63 bytes. It never starts with `-`,
# so it cannot be read as an option by createdb/pg_dump/dropdb, and it holds no
# quote, `$`, space or path separator, so it is safe in SQL, shell and paths.
DB_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{1,62}$")
# A public domain as nginx `server_name` and a certificate CN take it: DNS labels,
# optionally behind one leading `*.` wildcard.
DOMAIN_RE = re.compile(
    r"^(\*\.)?([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*"
    r"[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$"
)
# A git branch to clone: a plain ref name, no `..`, never an option.
BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,99}$")
# The Odoo version as typed at install: a major, optionally with `.0`.
VERSION_RE = re.compile(r"^[0-9]{1,2}(\.0)?$")
# A PostgreSQL host: a DNS name, an IPv4/IPv6 literal, or a Unix socket directory.
DB_HOST_RE = re.compile(
    r"^([A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?|[0-9A-Fa-f:.]{2,45}|/[A-Za-z0-9/._-]{0,200})$"
)


# Names a new instance must not take: the instance name is also its Linux user, its
# systemd unit, its home and log names, so a system account or service name would
# hand the tool an existing account (``userdel -r backup`` removes /var/backups) or
# shadow a distribution unit (``/etc/systemd/system/nginx.service``).
RESERVED_INSTANCE_NAMES = frozenset({
    # Debian/Ubuntu base accounts and common service accounts
    "root", "daemon", "bin", "sys", "sync", "games", "man", "lp", "mail", "news", "uucp",
    "proxy", "backup", "list", "irc", "gnats", "nobody", "messagebus", "syslog", "sshd",
    "uuidd", "tcpdump", "tss", "landscape", "pollinate", "lxd", "usbmux", "dnsmasq",
    "polkitd", "postfix", "ntp", "chrony", "ubuntu", "debian", "admin", "www_data",
    # services this tool configures or relies on
    "postgres", "postgresql", "nginx", "ssh", "cron", "fail2ban", "ufw", "rsyslog",
    "logrotate", "certbot", "systemd", "networking", "docker", "snapd", "dbus", "odoo",
    # directory names the tool keeps beside the instances
    "ssl", "default", "filestore", "sessions",
})


def reserved_name_error(name: str) -> str | None:
    if name in RESERVED_INSTANCE_NAMES:
        return "That name is a system account or service name. Choose another instance name."
    return None


def is_valid_db_name(name: str) -> bool:
    """True if ``name`` is a database name Odoo accepts and every command can take."""
    return bool(DB_NAME_RE.fullmatch(name or ""))


def domain_error(domain: str) -> str | None:
    if len(domain or "") <= 253 and DOMAIN_RE.fullmatch(domain or ""):
        return None
    return "invalid domain. Use a DNS name such as erp.example.com (optionally *.example.com)."


def branch_error(branch: str) -> str | None:
    value = branch or ""
    if BRANCH_RE.fullmatch(value) and ".." not in value and not value.endswith((".lock", "/")):
        return None
    return "invalid repo branch. Use a branch name such as 18.0."


def version_error(version: str) -> str | None:
    if VERSION_RE.fullmatch(version or ""):
        return None
    return "invalid Odoo version. Use a major such as 18 or 18.0."


def ip_error(address: str) -> str | None:
    try:
        ipaddress.ip_address(address or "")
    except ValueError:
        return "invalid IP address. Use an address such as 10.0.0.5."
    return None


def db_host_error(host: str) -> str | None:
    value = host or ""
    # Empty is Odoo's own default: connect through the local Unix socket.
    if value == "" or (DB_HOST_RE.fullmatch(value) and ".." not in value):
        return None
    return "invalid DB host. Use a host name, an IP address or a socket directory."


def host_cidr(address: str) -> str:
    """``address`` as a single-host CIDR: ``/32`` for IPv4, ``/128`` for IPv6."""
    parsed = ipaddress.ip_address(address)
    return f"{parsed}/{parsed.max_prefixlen}"

# Local (non-networked) DB host markers: an SSL mode is never forced for these.
LOCAL_DB_HOSTS = frozenset(
    {"", "false", "none", "localhost", "127.0.0.1", "::1", "/var/run/postgresql"}
)


def generate_secret() -> str:
    """A strong URL-safe random secret (stdlib only), ~32 printable chars."""
    return secrets.token_urlsafe(24)


@dataclass
class InstanceConfig:
    base_instances_dir: ClassVar[str] = "/opt/odoo"
    instance: str
    version: str = "18"
    repo_branch: str = "18.0"
    # The core repository: "odoo" (official) or "ocb" (OCA backports).
    core: str = "odoo"
    # The interpreter the venv is built with, and where it comes from: "host"
    # (python3) or "uv" (installed under support.UV_PYTHON_DIR). Empty: host.
    python: str = ""
    python_source: str = ""
    # Odoo's data_dir (filestores, sessions). New installs put it outside the home,
    # in /var/lib/odoo/<instance>; empty leaves Odoo's default (~/.local/share/Odoo).
    data_dir: str = ""
    domain: str = "odooprodserver.local"
    http_port: int = 8069
    gevent_port: int = 8072
    db_host: str = "127.0.0.1"
    db_port: int = 5432
    db_user: str = ""
    db_password: str = ""
    db_name: str = ""
    app_server_ip: str = "127.0.0.1"
    odoo_admin_passwd: str = ""

    # The certificate and key an HTTPS vhost names when they are not the tool's own
    # (Let's Encrypt, or the ones an existing vhost already names). Empty: the files
    # under nginx_ssl_dir.
    tls_cert: str = ""
    tls_key: str = ""

    # Production-posture settings (rendered into odoo.conf).
    list_db: bool = False
    dbfilter: str = ""
    db_sslmode: str = ""
    workers: int = 2
    max_cron_threads: int = 1
    limit_memory_soft: int = 2147483648
    limit_memory_hard: int = 2684354560
    limit_request: int = 8192
    limit_time_cpu: int = 3600
    limit_time_real: int = 7200

    @property
    def odoo_user(self) -> str:
        return self.instance

    @property
    def odoo_major(self) -> int:
        """Odoo major version parsed from ``version`` (e.g. ``18.0`` → ``18``).

        Drives version-adaptive rendering (``gevent_port`` vs ``longpolling_port``
        and the Nginx live-chat location). Falls back to a modern default (18)
        when the value is not parseable, so new stacks render the current shape.
        """
        match = re.search(r"\d+", self.version or "")
        return int(match.group(0)) if match else 18

    @property
    def is_remote_db_host(self) -> bool:
        return (self.db_host or "").strip().lower() not in LOCAL_DB_HOSTS

    @property
    def gevent_port_key(self) -> str:
        """Config key for the live-chat/bus port: ``gevent_port`` on Odoo ≥ 16,
        ``longpolling_port`` on ≤ 15 (renamed in Odoo 16)."""
        return "gevent_port" if self.odoo_major >= 16 else "longpolling_port"

    @property
    def live_chat_location(self) -> str:
        """Nginx proxy location for the live-chat/bus: ``/websocket`` on Odoo ≥ 16,
        ``/longpolling/poll`` on ≤ 15."""
        return "/websocket" if self.odoo_major >= 16 else "/longpolling/poll"

    @property
    def odoo_home(self) -> str:
        return f"{self.base_instances_dir}/{self.instance}"

    @property
    def managed_data_dir(self) -> str:
        """The data dir a new install gives the instance, outside its home."""
        return f"/var/lib/odoo/{self.instance}"

    @property
    def odoo_conf_dir(self) -> str:
        return f"/etc/odoo/{self.instance}"

    @property
    def odoo_conf_file(self) -> str:
        return f"{self.odoo_conf_dir}/{self.instance}.conf"

    @property
    def odoo_service(self) -> str:
        return self.instance

    @property
    def odoo_log_file(self) -> str:
        return f"/var/log/odoo/{self.instance}.log"

    @property
    def logrotate_config_file(self) -> str:
        return f"/etc/logrotate.d/odoo-{self.instance}"

    @property
    def nginx_access_log(self) -> str:
        return f"/var/log/nginx/{self.instance}.access.log"

    @property
    def nginx_error_log(self) -> str:
        return f"/var/log/nginx/{self.instance}.error.log"

    @property
    def nginx_http_name(self) -> str:
        return f"{self.instance}-http.conf"

    @property
    def nginx_https_name(self) -> str:
        return f"{self.instance}-https.conf"

    @property
    def nginx_ssl_dir(self) -> str:
        return f"/etc/nginx/ssl/{self.instance}"

    @property
    def domain_token(self) -> str:
        token = self.domain.lower().replace("*", "wildcard")
        return re.sub(r"[^a-z0-9._-]+", "_", token)

    @property
    def ssl_cert_file(self) -> str:
        return f"{self.nginx_ssl_dir}/{self.domain_token}.server.crt"

    @property
    def ssl_key_file(self) -> str:
        return f"{self.nginx_ssl_dir}/{self.domain_token}.server.key"

    @property
    def ssl_intermediate_file(self) -> str:
        return f"{self.nginx_ssl_dir}/{self.domain_token}.intermediate.crt"

    @property
    def ssl_fullchain_file(self) -> str:
        return f"{self.nginx_ssl_dir}/{self.domain_token}.fullchain.crt"

    def normalize_defaults(self) -> None:
        """Fill deterministic, non-secret defaults. The DB user (an identifier,
        not a secret) may default to the instance name; secrets never do — see
        ``ensure_strong_secrets``."""
        if not self.db_user:
            self.db_user = self.instance

    def ensure_strong_secrets(self) -> None:
        """Fill blank secrets (DB password and Odoo master password) with a strong
        random value, never the guessable instance name."""
        if not self.db_password:
            self.db_password = generate_secret()
        if not self.odoo_admin_passwd:
            self.odoo_admin_passwd = generate_secret()

    def uses_instance_name_secret(self) -> bool:
        """True when a secret still equals the guessable instance-name default."""
        return self.instance in {self.db_password, self.odoo_admin_passwd}

    def suggested_dbfilter(self) -> str:
        """A recommended dbfilter to *propose* (never written automatically): the
        explicit value, else an exact match on the known DB name, else a host-based
        filter. A blank ``dbfilter`` means "no filter" and is left unwritten."""
        if self.dbfilter:
            return self.dbfilter
        if self.db_name:
            return f"^{self.db_name}$"
        return "^%d$"

    def validate_identifiers(self) -> None:
        errors: list[str] = []

        if not INSTANCE_NAME_RE.fullmatch(self.instance):
            errors.append(
                'invalid instance. Use the format: start with a lowercase letter and only [a-z0-9_] (max 32).'
            )

        if not POSTGRES_IDENTIFIER_RE.fullmatch(self.db_user):
            errors.append(
                'invalid db_user for PostgreSQL. Use the format: start with [a-z_] and only [a-z0-9_] (max 63).'
            )

        for error in (
            version_error(self.version),
            branch_error(self.repo_branch),
            domain_error(self.domain),
            db_host_error(self.db_host),
            ip_error(self.app_server_ip),
        ):
            if error:
                errors.append(error)
        if self.core not in ("odoo", "ocb"):
            errors.append("invalid core. Use odoo or ocb.")
        if self.python and not re.fullmatch(r"3\.[0-9]{1,2}", self.python):
            errors.append("invalid Python version. Use e.g. 3.12.")
        if self.data_dir and not re.fullmatch(r"/[A-Za-z0-9/._-]{1,200}", self.data_dir):
            errors.append("invalid data_dir. Use an absolute path.")
        if self.db_name and not is_valid_db_name(self.db_name):
            errors.append("invalid DB name. Use letters, digits, '_', '.' and '-' (2-63, no leading symbol).")

        if errors:
            raise ValueError(" ".join(errors))
