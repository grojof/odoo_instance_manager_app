"""Read-only external server audit report.

Discovers Odoo instances (services, configs, Nginx vhosts, filestores), inspects
TLS posture and versions, and renders a report the operator can optionally export.
Strictly read-only with respect to server configuration.
"""

from __future__ import annotations

import datetime
import os
import re
import shlex
import socket

from ..models import InstanceConfig
from ..planners import _is_local_db_host, _sql_literal
from ..prompts import ask_bool, ask_int, ask_text
from ..system import (
    list_instances,
    path_exists,
    read_odoo_conf,
    run,
    service_active,
    service_enabled,
)
from ..ui import level_tag, level_text, render_table, strip_ansi, title
from .common import (
    _command_output,
    _is_self_signed_certificate,
    _odoo_conf_candidates,
    _quote,
    _read_text_file,
)


def _collect_system_overview() -> list[list[str]]:
    hostname = socket.gethostname()
    os_release = _read_text_file("/etc/os-release")
    pretty_name = ""
    for line in os_release.splitlines():
        if line.startswith("PRETTY_NAME="):
            pretty_name = line.split("=", 1)[1].strip().strip('"')
            break

    rows = [
        ["Hostname", hostname],
        ["SO", pretty_name or "no detectado"],
        ["Kernel", _command_output("uname -r") or "no detectado"],
        ["Arquitectura", _command_output("uname -m") or "no detectada"],
        ["Virtualización", _command_output("systemd-detect-virt") or "no detectada"],
        ["Uptime", _command_output("uptime -p") or "no detectado"],
        ["IP(s)", _command_output("hostname -I") or "no detectadas"],
        ["Python3 (sistema)", _command_output("python3 --version") or "no detectado"],
        ["Python3 path", _command_output("command -v python3") or "no detectado"],
        ["PostgreSQL client", _command_output("psql --version") or "no detectado"],
        ["Nginx", _command_output("nginx -v 2>&1") or "no detectado"],
    ]
    return rows


def _list_odoo_service_names() -> list[str]:
    service_lines = _command_output(
        "systemctl list-unit-files --type=service --no-legend --no-pager | awk '{print $1}'"
    )
    if not service_lines:
        return []

    services: list[str] = []
    for unit in service_lines.splitlines():
        service = unit.strip()
        if not service.endswith(".service"):
            continue
        unit_content = _command_output(f"systemctl cat {_quote(service)} 2>/dev/null")
        if "odoo-bin" in unit_content or "Description=Odoo" in unit_content:
            services.append(service[:-8])

    return sorted(set(services))


def _safe_find_paths(
    roots: list[str],
    entry_type: str,
    pattern: str,
    max_depth: int = 6,
    max_items: int = 300,
) -> list[str]:
    existing_roots = [root for root in roots if os.path.isdir(root)]
    if not existing_roots:
        return []

    roots_expr = " ".join(_quote(root) for root in existing_roots)
    cmd = (
        f"find {roots_expr} -maxdepth {max_depth} -type {entry_type} -iname {shlex.quote(pattern)} "
        f"2>/dev/null | head -n {max_items}"
    )
    output = _command_output(cmd)
    if not output:
        return []
    return sorted(set(line.strip() for line in output.splitlines() if line.strip()))


def _is_backup_like_name(name: str) -> bool:
    lowered = name.lower()
    markers = ["bak", "backup", "old", "orig", "save", "disabled", "~", ".dpkg-"]
    return any(marker in lowered for marker in markers)


def _is_valid_odoo_conf_file(path: str) -> bool:
    if not path or not os.path.isfile(path):
        return False

    if _is_backup_like_name(os.path.basename(path)):
        return False

    values = read_odoo_conf(path)
    if not values:
        return False

    expected_keys = {
        "addons_path",
        "http_port",
        "gevent_port",
        "db_host",
        "db_port",
        "db_user",
        "admin_passwd",
        "data_dir",
    }
    return len([key for key in expected_keys if key in values]) >= 2


def _discover_odoo_named_directories() -> list[str]:
    return _safe_find_paths(["/etc", "/opt", "/srv", "/home", "/var/lib"], "d", "*odoo*", max_depth=6)


def _discover_nginx_odoo_paths(service_names: list[str]) -> list[str]:
    paths: set[str] = set()
    nginx_dirs = ["/etc/nginx/sites-available", "/etc/nginx/sites-enabled"]
    for nginx_dir in nginx_dirs:
        if not os.path.isdir(nginx_dir):
            continue

        for name in sorted(os.listdir(nginx_dir)):
            file_path = os.path.join(nginx_dir, name)
            if os.path.islink(file_path):
                file_path = os.path.realpath(file_path)
            if not os.path.isfile(file_path):
                continue

            if _is_backup_like_name(os.path.basename(file_path)):
                continue

            content = _read_text_file(file_path).lower()
            if not content:
                continue

            if "odoo" in content or "odoochat" in content:
                paths.add(file_path)
                continue

            if "proxy_pass" in content and "server_name" in content and "127.0.0.1:" in content:
                paths.add(file_path)
                continue

            for service_name in service_names:
                if service_name.lower() in content:
                    paths.add(file_path)
                    break

    return sorted(paths)


def _discover_filestore_roots(
    service_names: list[str],
    conf_paths: list[str],
) -> list[str]:
    roots: set[str] = set()

    for conf_path in conf_paths:
        values = read_odoo_conf(conf_path)
        data_dir = values.get("data_dir", "").strip()
        if data_dir:
            roots.add(f"{data_dir}/filestore")

    for service_name in service_names:
        execstart = _parse_service_execstart(service_name)
        odoo_home = _extract_odoo_home_from_execstart(execstart)
        if odoo_home:
            roots.add(f"{odoo_home}/.local/share/Odoo/filestore")
        roots.add(f"/opt/odoo/{service_name}/.local/share/Odoo/filestore")

    for path in _safe_find_paths(["/opt", "/srv", "/home", "/var/lib"], "d", "filestore", max_depth=7):
        if "/.ssh/" in path or path.endswith("/.ssh/filestore"):
            continue
        roots.add(path)

    existing = [
        path
        for path in sorted(roots)
        if os.path.isdir(path) and "/.ssh/" not in path and not path.endswith("/.ssh/filestore")
    ]
    return existing


def _cell_multiline(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    return text.replace(", ", ",\n")


def _guess_instance_from_conf_path(conf_path: str) -> str:
    match = re.search(r"/etc/odoo/([^/]+)/[^/]+\.conf$", conf_path)
    if match:
        return match.group(1)

    match = re.search(r"/etc/([^/]+)/odoo\.conf$", conf_path)
    if match:
        return match.group(1)

    file_name = os.path.basename(conf_path)
    lower_file = file_name.lower()
    if lower_file.startswith("odoo") and lower_file.endswith(".conf") and not _is_backup_like_name(lower_file):
        return file_name[:-5]

    base = os.path.basename(os.path.dirname(conf_path))
    if base and base not in {"etc", "filter.d", "sites-available", "sites-enabled"}:
        return base
    return ""


def _parse_service_execstart(service_name: str) -> str:
    unit_content = _command_output(
        f"systemctl cat {_quote(service_name + '.service')} 2>/dev/null"
    )
    for raw_line in unit_content.splitlines():
        line = raw_line.strip()
        if line.startswith("ExecStart="):
            return line.split("=", 1)[1].strip()
    return ""


def _extract_python_from_execstart(execstart: str) -> str:
    if not execstart:
        return ""
    parts = shlex.split(execstart)
    if not parts:
        return ""
    candidate = parts[0]
    return candidate if os.path.exists(candidate) else ""


def _extract_odoo_home_from_execstart(execstart: str) -> str:
    if not execstart:
        return ""
    parts = shlex.split(execstart)
    for idx, token in enumerate(parts):
        if token.endswith("odoo-bin"):
            if token.endswith("/odoo/odoo-bin"):
                return token[: -len("/odoo/odoo-bin")]
            if token.endswith("/odoo-bin"):
                return token[: -len("/odoo-bin")]
            return os.path.dirname(token)
        if token == "-c" and idx + 1 < len(parts):
            conf_path = parts[idx + 1]
            values = read_odoo_conf(conf_path)
            addons = values.get("addons_path", "")
            if addons:
                first = addons.split(",", 1)[0]
                suffix = "/odoo/addons"
                if first.endswith(suffix):
                    return first[: -len(suffix)]
    return ""


def _extract_conf_from_execstart(execstart: str) -> str:
    if not execstart:
        return ""
    parts = shlex.split(execstart)
    for idx, token in enumerate(parts):
        if token == "-c" and idx + 1 < len(parts):
            return parts[idx + 1]
        if token.startswith("--config="):
            return token.split("=", 1)[1]
    return ""


def _collect_service_contexts() -> list[dict[str, str]]:
    contexts: list[dict[str, str]] = []
    for service_name in _list_odoo_service_names():
        execstart = _parse_service_execstart(service_name)
        python_path = _extract_python_from_execstart(execstart)
        odoo_home = _extract_odoo_home_from_execstart(execstart)
        conf_hint = _extract_conf_from_execstart(execstart)
        if not conf_hint:
            for default_conf in _odoo_conf_candidates(service_name):
                if os.path.isfile(default_conf):
                    conf_hint = default_conf
                    break

        contexts.append(
            {
                "service": service_name,
                "execstart": execstart,
                "python_path": python_path,
                "odoo_home": odoo_home,
                "conf_hint": conf_hint,
            }
        )
    return contexts


def _discover_odoo_conf_paths_from_contexts(
    contexts: list[dict[str, str]],
) -> list[str]:
    conf_paths: set[str] = set()

    for context in contexts:
        service_name = context.get("service", "")
        conf_hint = context.get("conf_hint", "")
        odoo_home = context.get("odoo_home", "")
        python_path = context.get("python_path", "")

        if conf_hint and _is_valid_odoo_conf_file(conf_hint):
            conf_paths.add(conf_hint)

        focused_roots: set[str] = set()
        if service_name:
            focused_roots.add(f"/etc/{service_name}")
            focused_roots.add(f"/etc/odoo/{service_name}")
        if conf_hint:
            focused_roots.add(os.path.dirname(conf_hint))
        if odoo_home:
            focused_roots.add(odoo_home)
            focused_roots.add(f"{odoo_home}/odoo")
        if python_path:
            focused_roots.add(os.path.dirname(python_path))
            focused_roots.add(os.path.dirname(os.path.dirname(python_path)))

        roots = [root for root in sorted(focused_roots) if root and os.path.isdir(root)]
        if roots:
            for path in _safe_find_paths(roots, "f", "*.conf", max_depth=5, max_items=80):
                if _is_valid_odoo_conf_file(path):
                    conf_paths.add(path)
            for path in _safe_find_paths(roots, "f", "odoo.conf", max_depth=5, max_items=60):
                if _is_valid_odoo_conf_file(path):
                    conf_paths.add(path)
            for path in _safe_find_paths(roots, "f", "*odoo*.conf", max_depth=5, max_items=80):
                if _is_valid_odoo_conf_file(path):
                    conf_paths.add(path)

    if not conf_paths:
        fallback_roots: list[str] = []
        if os.path.isdir("/etc/odoo"):
            fallback_roots.append("/etc/odoo")

        for name in sorted(os.listdir("/etc")) if os.path.isdir("/etc") else []:
            path = f"/etc/{name}"
            if os.path.isdir(path) and "odoo" in name.lower():
                fallback_roots.append(path)

        fallback_roots.append("/etc")

        if os.path.isdir("/etc/odoo"):
            for path in _safe_find_paths(["/etc/odoo"], "f", "*.conf", max_depth=6, max_items=300):
                if _is_valid_odoo_conf_file(path):
                    conf_paths.add(path)
        for path in _safe_find_paths(fallback_roots, "f", "odoo.conf", max_depth=6, max_items=200):
            if _is_valid_odoo_conf_file(path):
                conf_paths.add(path)
        for path in _safe_find_paths(fallback_roots, "f", "*odoo*.conf", max_depth=6, max_items=250):
            if _is_valid_odoo_conf_file(path):
                conf_paths.add(path)

    return sorted(conf_paths)


def _parse_nginx_tls_metadata(path: str) -> tuple[str, str, str]:
    content = _read_text_file(path)
    if not content:
        return "", "", ""

    server_name = ""
    cert_path = ""
    key_path = ""
    for raw_line in content.splitlines():
        line = raw_line.strip().rstrip(";")
        if line.startswith("server_name ") and not server_name:
            server_name = line.split(maxsplit=1)[1].strip()
        elif line.startswith("ssl_certificate ") and not cert_path:
            cert_path = line.split(maxsplit=1)[1].strip()
        elif line.startswith("ssl_certificate_key ") and not key_path:
            key_path = line.split(maxsplit=1)[1].strip()
    return server_name, cert_path, key_path


def _certificate_metadata(cert_path: str) -> dict[str, str]:
    if not cert_path or not path_exists(cert_path):
        return {"issuer": "", "subject": "", "not_after": "", "serial": ""}

    result = run(
        f"openssl x509 -in {_quote(cert_path)} -noout -issuer -subject -enddate -serial",
        check=False,
    )
    if result.returncode != 0:
        return {"issuer": "", "subject": "", "not_after": "", "serial": ""}

    issuer = ""
    subject = ""
    not_after = ""
    serial = ""
    for line in result.stdout.splitlines():
        raw = line.strip()
        if raw.startswith("issuer="):
            issuer = raw[len("issuer=") :].strip()
        elif raw.startswith("subject="):
            subject = raw[len("subject=") :].strip()
        elif raw.startswith("notAfter="):
            not_after = raw[len("notAfter=") :].strip()
        elif raw.startswith("serial="):
            serial = raw[len("serial=") :].strip()

    return {
        "issuer": issuer,
        "subject": subject,
        "not_after": not_after,
        "serial": serial,
    }


def _certificate_expiry_status(cert_path: str, threshold_days: int) -> tuple[str, str]:
    if not cert_path or not path_exists(cert_path):
        return "MISSING", "certificado no encontrado"

    result = run(
        f"openssl x509 -in {_quote(cert_path)} -noout -checkend {threshold_days * 86400}",
        check=False,
    )
    if result.returncode == 0:
        return "OK", f"vigente > {threshold_days} días"

    enddate = run(
        f"openssl x509 -in {_quote(cert_path)} -noout -enddate",
        check=False,
    )
    expires_text = ""
    if enddate.returncode == 0 and enddate.stdout.strip().startswith("notAfter="):
        expires_text = enddate.stdout.strip().split("=", 1)[1].strip()

    if expires_text:
        return "WARN", f"caduca antes de {threshold_days} días ({expires_text})"
    return "ERROR", "no se pudo validar expiración"


def _list_local_postgres_databases(instance: str, db_user: str) -> list[str]:
    instance_literal = _sql_literal(instance)
    db_user_literal = _sql_literal(db_user)
    sql = (
        "SELECT datname "
        "FROM pg_database d "
        "JOIN pg_roles r ON d.datdba = r.oid "
        "WHERE d.datistemplate = false "
        f"AND (d.datname LIKE '{instance_literal}%' OR r.rolname = '{db_user_literal}') "
        "ORDER BY d.datname;"
    )
    result = run(
        f"sudo -u postgres psql -d postgres -tA -c {shlex.quote(sql)}",
        check=False,
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _detect_tls_cert_type(cert_path: str, key_path: str) -> str:
    if not cert_path and not key_path:
        return "sin TLS"
    if "/etc/letsencrypt/" in cert_path or "/etc/letsencrypt/" in key_path:
        return "Let's Encrypt"
    if cert_path and _is_self_signed_certificate(cert_path):
        return "Autofirmado"
    if cert_path and key_path:
        return "Personalizado"
    return "TLS incompleto"


def _nginx_matches_instance(
    content: str,
    instance: str,
    service_name: str,
    http_port: str,
    gevent_port: str,
    conf_path: str,
    data_dir: str,
) -> bool:
    lower = content.lower()
    tokens = [
        instance.lower(),
        service_name.lower(),
        conf_path.lower(),
        data_dir.lower(),
    ]
    for token in tokens:
        if token and token in lower:
            return True

    if http_port.isdigit() and f":{http_port}" in lower:
        return True
    if gevent_port.isdigit() and f":{gevent_port}" in lower:
        return True

    return False


def _detect_odoo_release_version(odoo_home: str) -> str:
    if not odoo_home:
        return ""
    release_path = f"{odoo_home}/odoo/odoo/release.py"
    content = _read_text_file(release_path)
    if not content:
        return ""

    version_line = ""
    for line in content.splitlines():
        if line.strip().startswith("version_info"):
            version_line = line
            break
    if not version_line:
        return ""

    match = re.search(r"\((\d+),\s*(\d+)", version_line)
    if match:
        return f"{match.group(1)}.{match.group(2)}"
    return ""


def _collect_external_instance_rows(
    service_contexts: list[dict[str, str]],
    conf_paths: list[str],
    nginx_paths: list[str],
    filestore_roots: list[str],
) -> list[list[str]]:
    service_names = [context.get("service", "") for context in service_contexts if context.get("service")]
    service_context_by_name = {
        context.get("service", ""): context
        for context in service_contexts
        if context.get("service")
    }

    detected: set[str] = set(list_instances(InstanceConfig.base_instances_dir))
    detected.update(service_names)
    for conf_path in conf_paths:
        guessed = _guess_instance_from_conf_path(conf_path)
        if guessed:
            detected.add(guessed)

    filestore_db_map: dict[str, set[str]] = {}
    for root in filestore_roots:
        db_names: set[str] = set()
        if os.path.isdir(root):
            try:
                for name in os.listdir(root):
                    if os.path.isdir(os.path.join(root, name)) and not name.startswith("."):
                        db_names.add(name)
            except OSError:
                pass
        filestore_db_map[root] = db_names

    rows: list[list[str]] = []
    for instance in sorted(detected):
        config = InstanceConfig(instance=instance)
        config.normalize_defaults()

        service_state = level_text("OK", "activo") if service_active(config.odoo_service) else level_text("MISSING", "detenido")
        autostart_state = level_text("OK", "sí") if service_enabled(config.odoo_service) else level_text("INFO", "no")

        instance_conf_paths = [
            path
            for path in conf_paths
            if f"/{instance}/" in path or path.endswith(f"/{instance}.conf") or f"/{instance}-" in path
        ]
        preferred_conf = config.odoo_conf_file if path_exists(config.odoo_conf_file) else (instance_conf_paths[0] if instance_conf_paths else "")
        conf_values = read_odoo_conf(preferred_conf) if preferred_conf else {}
        http_port = conf_values.get("http_port", "") or ""
        gevent_port = conf_values.get("gevent_port", "") or ""
        db_port = conf_values.get("db_port", "") or ""
        db_host = conf_values.get("db_host", "") or ""
        db_user = conf_values.get("db_user", "") or config.db_user
        addons_path = conf_values.get("addons_path", "") or ""
        workers = conf_values.get("workers", "") or ""
        data_dir = conf_values.get("data_dir", "").strip() if conf_values else ""
        if not data_dir:
            data_dir = f"{config.odoo_home}/.local/share/Odoo"
        filestore_root = f"{data_dir}/filestore"

        filestore_dbs: list[str] = []
        if os.path.isdir(filestore_root):
            filestore_dbs = sorted(
                [
                    name
                    for name in os.listdir(filestore_root)
                    if os.path.isdir(os.path.join(filestore_root, name)) and not name.startswith(".")
                ]
            )

        local_db_names: list[str] = []
        if _is_local_db_host(db_host):
            local_db_names = _list_local_postgres_databases(instance, db_user)
        local_db_set = set(local_db_names)

        context = service_context_by_name.get(config.odoo_service, {})
        python_path = context.get("python_path", "")
        python_version = _command_output(f"{_quote(python_path)} --version") if python_path else ""
        odoo_home = context.get("odoo_home", "") or config.odoo_home
        odoo_version = _detect_odoo_release_version(odoo_home)

        nginx_hits: list[str] = []
        for path in nginx_paths:
            content = _read_text_file(path)
            if not content:
                continue
            if _nginx_matches_instance(
                content=content,
                instance=instance,
                service_name=config.odoo_service,
                http_port=http_port,
                gevent_port=gevent_port,
                conf_path=preferred_conf,
                data_dir=data_dir,
            ):
                nginx_hits.append(path)

        if not nginx_hits:
            for path in nginx_paths:
                content = _read_text_file(path)
                if not content:
                    continue
                if "odoo" in content.lower() and (
                    f"/etc/{instance}/" in content.lower() or f"/opt/odoo/{instance}" in content.lower()
                ):
                    nginx_hits.append(path)

        filestore_hits: list[str] = []
        filestore_match_dbs: set[str] = set()
        for root in filestore_roots:
            root_db_names = filestore_db_map.get(root, set())
            if local_db_set and root_db_names.intersection(local_db_set):
                filestore_hits.append(root)
                filestore_match_dbs.update(root_db_names.intersection(local_db_set))
                continue

            if root == filestore_root or root.startswith(filestore_root) or instance in root:
                filestore_hits.append(root)
                filestore_match_dbs.update(root_db_names)

        if local_db_set and not filestore_match_dbs:
            filestore_match_dbs = local_db_set

        filestore_db_summary = ", ".join(sorted(filestore_match_dbs)) if filestore_match_dbs else ", ".join(filestore_dbs[:8])

        cert_candidates: set[str] = set()
        key_candidates: set[str] = set()
        server_name_candidates: set[str] = set()
        for nginx_path in nginx_hits:
            server_name, cert_path, key_path = _parse_nginx_tls_metadata(nginx_path)
            if server_name:
                server_name_candidates.add(server_name)
            if cert_path:
                cert_candidates.add(cert_path)
            if key_path:
                key_candidates.add(key_path)

        cert_summary = ", ".join(sorted(cert_candidates)) if cert_candidates else ""
        key_summary = ", ".join(sorted(key_candidates)) if key_candidates else ""
        server_name_summary = ", ".join(sorted(server_name_candidates)) if server_name_candidates else ""
        tls_type = _detect_tls_cert_type(next(iter(cert_candidates), ""), next(iter(key_candidates), ""))
        cert_meta = _certificate_metadata(next(iter(cert_candidates), ""))

        addons_summary = ""
        if addons_path:
            addon_items = [item.strip() for item in addons_path.split(",") if item.strip()]
            addons_summary = ", ".join(addon_items[:3]) + (" ..." if len(addon_items) > 3 else "")

        rows.append(
            [
                instance,
                service_state,
                autostart_state,
                odoo_version or "no detectada",
                http_port,
                gevent_port,
                db_host,
                db_user,
                db_port,
                workers,
                python_version or "",
                python_path or "",
                preferred_conf or "",
                data_dir,
                filestore_db_summary + (" ..." if len(filestore_match_dbs) > 8 else ""),
                addons_summary,
                server_name_summary,
                cert_summary,
                key_summary,
                tls_type,
                cert_meta.get("issuer", ""),
                cert_meta.get("subject", ""),
                cert_meta.get("not_after", ""),
                cert_meta.get("serial", ""),
                ", ".join(local_db_names),
                str(len(nginx_hits)),
                str(len(filestore_hits)),
            ]
        )

    return rows


def _collect_odoo_services_rows(service_contexts: list[dict[str, str]]) -> list[list[str]]:
    rows: list[list[str]] = []
    for context in service_contexts:
        service_name = context.get("service", "")
        if not service_name:
            continue
        rows.append(
            [
                service_name,
                level_text("OK", "activo") if service_active(service_name) else level_text("MISSING", "detenido"),
                level_text("OK", "sí") if service_enabled(service_name) else level_text("INFO", "no"),
                context.get("python_path", ""),
                context.get("odoo_home", ""),
                context.get("conf_hint", ""),
            ]
        )
    return rows


def external_server_report() -> None:
    print(f"\n{title('Informe para servidor externo')}")

    report_sections: list[str] = []

    service_contexts = _collect_service_contexts()
    service_names = [context.get("service", "") for context in service_contexts if context.get("service")]

    conf_paths = _discover_odoo_conf_paths_from_contexts(service_contexts)
    nginx_paths = _discover_nginx_odoo_paths(service_names)
    filestore_roots = _discover_filestore_roots(service_names, conf_paths)
    named_dirs = _discover_odoo_named_directories()

    system_rows = _collect_system_overview()
    system_rows.extend(
        [
            ["PostgreSQL service", level_text("OK", "activo") if service_active("postgresql") else level_text("MISSING", "detenido")],
            ["PostgreSQL autostart", level_text("OK", "sí") if service_enabled("postgresql") else level_text("INFO", "no")],
            ["Nginx service", level_text("OK", "activo") if service_active("nginx") else level_text("MISSING", "detenido")],
            ["Nginx autostart", level_text("OK", "sí") if service_enabled("nginx") else level_text("INFO", "no")],
            ["Nginx test", _command_output("nginx -t 2>&1 | tail -n 1") or "no disponible"],
        ]
    )
    system_table = render_table(["Campo", "Valor"], system_rows)
    print(f"\n{title('Resumen del servidor')}\n{system_table}")
    report_sections.append("Resumen del servidor\n" + strip_ansi(system_table))

    services_rows = _collect_odoo_services_rows(service_contexts)
    services_table = render_table(
        ["Servicio", "Estado", "Autoarranque", "Python path", "Odoo home", "Config hint"],
        services_rows if services_rows else [["(sin servicios detectados)", "", "", "", "", ""]],
    )
    print(f"\n{title('Servicios Odoo detectados')}\n{services_table}")
    report_sections.append("Servicios Odoo detectados\n" + strip_ansi(services_table))

    artifacts_table = render_table(
        ["Tipo", "Cantidad", "Muestra"],
        [
            ["Dirs con 'odoo'", str(len(named_dirs)), ", ".join(named_dirs[:3]) or "-"],
            ["Configs Odoo", str(len(conf_paths)), ", ".join(conf_paths[:3]) or "-"],
            ["Configs Nginx relacionadas", str(len(nginx_paths)), ", ".join(nginx_paths[:3]) or "-"],
            ["Filestore roots", str(len(filestore_roots)), ", ".join(filestore_roots[:3]) or "-"],
        ],
    )
    print(f"\n{title('Artefactos detectados por búsqueda')}\n{artifacts_table}")
    report_sections.append("Artefactos detectados por búsqueda\n" + strip_ansi(artifacts_table))

    if conf_paths:
        conf_table = render_table(
            ["#", "Config Odoo"],
            [[str(idx), path] for idx, path in enumerate(conf_paths, start=1)],
        )
        print(f"\n{title('Archivos de configuración Odoo detectados')}\n{conf_table}")
        report_sections.append("Archivos de configuración Odoo detectados\n" + strip_ansi(conf_table))

    if nginx_paths:
        nginx_table = render_table(
            ["#", "Config Nginx"],
            [[str(idx), path] for idx, path in enumerate(nginx_paths, start=1)],
        )
        print(f"\n{title('Configs Nginx relacionadas con Odoo')}\n{nginx_table}")
        report_sections.append("Configs Nginx relacionadas con Odoo\n" + strip_ansi(nginx_table))

    if filestore_roots:
        filestore_rows: list[list[str]] = []
        for idx, root in enumerate(filestore_roots, start=1):
            db_count = 0
            try:
                db_count = len(
                    [
                        name
                        for name in os.listdir(root)
                        if os.path.isdir(os.path.join(root, name)) and not name.startswith(".")
                    ]
                )
            except OSError:
                db_count = 0
            filestore_rows.append([str(idx), root, str(db_count)])
        filestore_table = render_table(["#", "Filestore root", "DB dirs"], filestore_rows)
        print(f"\n{title('Filestores detectados')}\n{filestore_table}")
        report_sections.append("Filestores detectados\n" + strip_ansi(filestore_table))

    instance_rows = _collect_external_instance_rows(
        service_contexts=service_contexts,
        conf_paths=conf_paths,
        nginx_paths=nginx_paths,
        filestore_roots=filestore_roots,
    )
    odoo_rows: list[list[str]] = []
    python_rows: list[list[str]] = []
    nginx_rows: list[list[str]] = []
    for row in instance_rows:
        odoo_rows.append(
            [
                row[0],
                row[1],
                row[2],
                row[3],
                row[4],
                row[5],
                row[6],
                row[7],
                row[8],
                row[12],
                row[13],
                _cell_multiline(row[14]),
                _cell_multiline(row[24]),
            ]
        )
        python_rows.append(
            [
                row[0],
                row[10],
                row[25],
                row[26],
                _cell_multiline(row[15]),
            ]
        )
        nginx_rows.append(
            [
                row[0],
                _cell_multiline(row[16]),
                row[4],
                row[5],
                row[19],
                row[24],
                row[25],
            ]
        )

    odoo_table = render_table(
        [
            "Instancia",
            "Servicio",
            "Autoarranque",
            "Odoo",
            "HTTP",
            "gevent",
            "DB host",
            "DB user",
            "DB port",
            "Config Odoo",
            "Data dir",
            "Filestores",
            "DBs locales",
        ],
        odoo_rows if odoo_rows else [["(sin instancias detectadas)", "", "", "", "", "", "", "", "", "", "", "", ""]],
    )
    print(f"\n{title('Instancias: Odoo / rutas / DB')}\n{odoo_table}")
    report_sections.append("Instancias: Odoo / rutas / DB\n" + strip_ansi(odoo_table))

    python_table = render_table(
        ["Instancia", "Python", "Python path", "Workers", "Addons"],
        python_rows if python_rows else [["(sin instancias detectadas)", "", "", "", ""]],
    )
    print(f"\n{title('Instancias: Python')}\n{python_table}")
    report_sections.append("Instancias: Python\n" + strip_ansi(python_table))

    nginx_table_by_instance = render_table(
        ["Instancia", "server_name", "HTTP", "gevent", "TLS tipo", "Nginx cfgs", "Filestore roots"],
        nginx_rows if nginx_rows else [["(sin instancias detectadas)", "", "", "", "", "", ""]],
    )
    print(f"\n{title('Instancias: Nginx / puertos')}\n{nginx_table_by_instance}")
    report_sections.append("Instancias: Nginx / puertos\n" + strip_ansi(nginx_table_by_instance))

    cert_details_map: dict[str, dict[str, str | set[str]]] = {}
    for row in instance_rows:
        instance_name = row[0]
        server_names = [item.strip() for item in row[16].split(",") if item.strip()]
        cert_paths = [item.strip() for item in row[17].split(",") if item.strip()]
        key_paths = [item.strip() for item in row[18].split(",") if item.strip()]
        tls_type = row[19]
        issuer = row[20]
        subject = row[21]
        expires = row[22]
        serial = row[23]

        for cert_path in cert_paths:
            item = cert_details_map.setdefault(
                cert_path,
                {
                    "key": ", ".join(key_paths),
                    "type": tls_type,
                    "issuer": issuer,
                    "subject": subject,
                    "expires": expires,
                    "serial": serial,
                    "instances": set(),
                    "server_names": set(),
                },
            )
            instances = item["instances"]
            if isinstance(instances, set):
                instances.add(instance_name)
            names = item["server_names"]
            if isinstance(names, set):
                for name in server_names:
                    names.add(name)

    if cert_details_map:
        cert_rows: list[list[str]] = []
        for cert_path in sorted(cert_details_map):
            item = cert_details_map[cert_path]
            instances = item["instances"]
            server_names = item["server_names"]
            cert_rows.append(
                [
                    cert_path,
                    _cell_multiline(str(item["key"])),
                    str(item["type"]),
                    _cell_multiline(str(item["issuer"])),
                    _cell_multiline(str(item["subject"])),
                    str(item["expires"]),
                    ", ".join(sorted(instances)) if isinstance(instances, set) else "",
                    _cell_multiline(", ".join(sorted(server_names)) if isinstance(server_names, set) else ""),
                ]
            )

        cert_table = render_table(
            [
                "TLS cert",
                "TLS key",
                "Tipo",
                "Issuer",
                "Subject",
                "Expira",
                "Instancias",
                "server_name",
            ],
            cert_rows,
        )
        print(f"\n{title('Detalle de certificados TLS')}\n{cert_table}")
        report_sections.append("Detalle de certificados TLS\n" + strip_ansi(cert_table))

    run_active_checks = ask_bool(
        "¿Ejecutar comprobaciones activas de certificados TLS?",
        True,
    )
    if run_active_checks:
        threshold_days = ask_int(
            "Umbral de alerta para expiración TLS (días)",
            120,
        )
        cert_paths: set[str] = set(cert_details_map.keys())

        if cert_paths:
            check_rows: list[list[str]] = []
            for cert_path in sorted(cert_paths):
                status, detail = _certificate_expiry_status(cert_path, threshold_days)
                check_rows.append([level_tag(status), cert_path, detail])

            checks_table = render_table(["Estado", "Certificado", "Resultado"], check_rows)
            print(f"\n{title('Comprobaciones activas TLS')}\n{checks_table}")
            report_sections.append("Comprobaciones activas TLS\n" + strip_ansi(checks_table))
        else:
            info_message = level_text("INFO", "No hay rutas de certificados TLS detectadas para comprobación activa.")
            print(info_message)
            report_sections.append("Comprobaciones activas TLS\n" + strip_ansi(info_message))

    export_report = ask_bool("¿Quieres exportar el informe a archivo?", True)
    if not export_report:
        print(level_text("INFO", "Exportación omitida por el usuario."))
        return

    now = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    host = socket.gethostname()
    default_path = f"./reports/{host}_{now}.txt"
    export_path = ask_text("Ruta de exportación del informe", default_path, required=True)

    export_dir = os.path.dirname(export_path) or "."
    os.makedirs(export_dir, exist_ok=True)
    with open(export_path, "w", encoding="utf-8") as file_handle:
        file_handle.write("\n\n".join(report_sections) + "\n")

    print(level_text("OK", f"Informe exportado en: {export_path}"))
