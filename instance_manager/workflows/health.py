"""Read-only health check for an instance: service, HTTP, DB, and disk."""

from __future__ import annotations

import urllib.error
import urllib.request

from ..models import InstanceConfig
from ..system import (
    path_exists,
    read_odoo_conf,
    run,
    service_active,
    service_enabled,
)
from ..ui import level_tag, level_text, render_table, title
from .common import _quote, _resolve_data_dir


def _http_probe(port: str) -> tuple[bool, str]:
    """GET the instance's local HTTP port; any 2xx/3xx counts as responding."""
    if not port.isdigit():
        return False, "puerto HTTP no numérico en config"
    for path in ("/web/health", "/web/login", "/"):
        url = f"http://127.0.0.1:{port}{path}"
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:  # noqa: S310 (local only)
                return 200 <= resp.status < 400, f"HTTP {resp.status} en {path}"
        except urllib.error.HTTPError as error:
            # A 3xx/4xx still means the server answered.
            return 200 <= error.code < 500, f"HTTP {error.code} en {path}"
        except (urllib.error.URLError, OSError):
            continue
    return False, "sin respuesta en 127.0.0.1"


def _db_probe(config: InstanceConfig, conf: dict[str, str]) -> tuple[bool, str]:
    db_host = conf.get("db_host", config.db_host) or "127.0.0.1"
    db_port = conf.get("db_port", str(config.db_port)) or "5432"
    db_user = conf.get("db_user", config.db_user) or config.instance
    db_password = conf.get("db_password", "")
    cmd = (
        f"PGPASSWORD={_quote(db_password)} psql -h {_quote(db_host)} -p {_quote(str(db_port))} "
        f"-U {_quote(db_user)} -d postgres -tAc 'SELECT 1' >/dev/null 2>&1"
    )
    ok = run(cmd, check=False).returncode == 0
    return ok, f"{db_user}@{db_host}:{db_port}"


def _disk_row(label: str, path: str) -> list[str]:
    if not path_exists(path):
        return [level_tag("INFO"), label, f"{path} (no existe)"]
    result = run(f"df -Ph {_quote(path)} | tail -1", check=False)
    parts = result.stdout.split()
    if len(parts) >= 5:
        used_pct = parts[4].rstrip("%")
        avail = parts[3]
        tag = "MISSING" if used_pct.isdigit() and int(used_pct) >= 90 else "OK"
        return [level_tag(tag), label, f"{avail} libres, {parts[4]} usado ({path})"]
    return [level_tag("INFO"), label, f"{path} (no medible)"]


def run_health_check(config: InstanceConfig) -> None:
    print(f"\n{title(f'Health check: {config.instance}')}")
    conf = read_odoo_conf(config.odoo_conf_file)

    rows: list[list[str]] = []

    active = service_active(config.odoo_service)
    enabled = service_enabled(config.odoo_service)
    rows.append(
        [
            level_tag("OK" if active else "MISSING"),
            "Servicio Odoo",
            ("activo" if active else "detenido/inexistente")
            + (", autoarranque sí" if enabled else ", autoarranque no"),
        ]
    )

    http_port = conf.get("http_port", str(config.http_port))
    http_ok, http_detail = _http_probe(http_port)
    rows.append([level_tag("OK" if http_ok else "MISSING"), "HTTP local", http_detail])

    db_ok, db_detail = _db_probe(config, conf)
    rows.append([level_tag("OK" if db_ok else "MISSING"), "Conexión DB", db_detail])

    rows.append(_disk_row("Disco (home)", config.odoo_home))
    rows.append(_disk_row("Disco (data dir)", _resolve_data_dir(config)))

    print(render_table(["Estado", "Chequeo", "Detalle"], rows))

    if not active:
        print(level_text("WARN", "El servicio no está activo: arráncalo desde 'Servicios instancias'."))
    elif not http_ok:
        print(level_text("WARN", "El servicio está activo pero no responde por HTTP; revisa el log de Odoo."))
