from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from typing import ClassVar

INSTANCE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
POSTGRES_IDENTIFIER_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")

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

        if errors:
            raise ValueError(" ".join(errors))
