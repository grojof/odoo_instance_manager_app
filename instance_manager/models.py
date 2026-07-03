from __future__ import annotations

import re
from dataclasses import dataclass
from typing import ClassVar

INSTANCE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
POSTGRES_IDENTIFIER_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


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

    @property
    def odoo_user(self) -> str:
        return self.instance

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
        if not self.db_user:
            self.db_user = self.instance
        if not self.db_password:
            self.db_password = self.instance
        if not self.odoo_admin_passwd:
            self.odoo_admin_passwd = self.instance

    def validate_identifiers(self) -> None:
        errors: list[str] = []

        if not INSTANCE_NAME_RE.fullmatch(self.instance):
            errors.append(
                "instance inválida. Usa formato: inicia con letra minúscula y solo [a-z0-9_] (máx 32)."
            )

        if not POSTGRES_IDENTIFIER_RE.fullmatch(self.db_user):
            errors.append(
                "db_user inválido para PostgreSQL. Usa formato: inicia con [a-z_] y solo [a-z0-9_] (máx 63)."
            )

        if errors:
            raise ValueError(" ".join(errors))
