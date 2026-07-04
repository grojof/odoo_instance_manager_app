from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass

from .i18n import t, tf
from .ui import level_text, style, title, wrap_plain_block


@dataclass
class Command:
    description: str
    command: str


def run(command: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["bash", "-lc", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"Command failed: {command}\n"
            f"exit={result.returncode}\n"
            f"stdout={result.stdout}\n"
            f"stderr={result.stderr}"
        )
    return result


def run_streaming(command: str) -> subprocess.CompletedProcess[str]:
    """Run a command, forwarding its output live while also capturing it.

    stdlib-only (``subprocess.Popen``): stderr is merged into stdout so combined
    output appears in real time — useful for long steps (apt/pip/pg_restore) that
    would otherwise sit silent. stdin is closed so a command never blocks waiting
    for input. Returns a ``CompletedProcess`` with the accumulated output.
    """
    process = subprocess.Popen(
        ["bash", "-lc", command],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    captured: list[str] = []
    assert process.stdout is not None
    for line in process.stdout:
        print(line, end="", flush=True)
        captured.append(line)
    process.stdout.close()
    returncode = process.wait()
    return subprocess.CompletedProcess(process.args, returncode, "".join(captured), "")


def require_root_for_apply() -> None:
    if os.geteuid() != 0:
        raise RuntimeError('To apply system changes, run as root (sudo).')


def command_ok(command: str) -> bool:
    return run(command, check=False).returncode == 0


def user_exists(username: str) -> bool:
    return command_ok(f"id -u '{username}' >/dev/null 2>&1")


def service_exists(service_name: str) -> bool:
    return command_ok(f"systemctl cat '{service_name}' >/dev/null 2>&1")


def service_active(service_name: str) -> bool:
    return command_ok(f"systemctl is-active --quiet '{service_name}'")


def service_enabled(service_name: str) -> bool:
    return command_ok(f"systemctl is-enabled --quiet '{service_name}'")


def path_exists(path: str) -> bool:
    return command_ok(f"test -e '{path}'")


def db_role_exists(role_name: str) -> bool:
    query = f"sudo -u postgres psql -tAc \"SELECT 1 FROM pg_roles WHERE rolname='{role_name}'\""
    result = run(query, check=False)
    return result.returncode == 0 and "1" in result.stdout


def database_exists(db_name: str) -> bool:
    query = f"sudo -u postgres psql -tAc \"SELECT 1 FROM pg_database WHERE datname='{db_name}'\""
    result = run(query, check=False)
    return result.returncode == 0 and "1" in result.stdout


def preview_commands(commands: list[Command]) -> None:
    """Render the plan as a readable list.

    Commands are shown below their description, indented and wrapped to the
    terminal width — long or multi-line commands (e.g. a heredoc that writes a
    config file) stay legible instead of overflowing a table column.
    """
    print(f"\n{title('Execution plan')}")
    indent = "     "
    body_width = max(20, shutil.get_terminal_size((100, 24)).columns - len(indent))
    for index, item in enumerate(commands, start=1):
        print(f"\n{style(f'[{index:02d}]', 'blue', 'bold')} {t(item.description)}")
        for chunk in wrap_plain_block(item.command, body_width):
            print(style(f"{indent}{chunk}", "dim"))


def apply_commands(commands: list[Command], stop_on_error: bool = True) -> None:
    for index, item in enumerate(commands, start=1):
        print(f"\n{style(f'[{index}/{len(commands)}]', 'blue', 'bold')} {t(item.description)}")
        # Stream output live so long steps (apt/pip/pg_restore) aren't silent.
        result = run_streaming(item.command)
        if result.returncode != 0:
            print(level_text("ERROR", tf('Command finished with code {}.', result.returncode)))
            if stop_on_error:
                raise RuntimeError(f"Failed running: {item.command}")


def list_dirs(base_path: str) -> list[str]:
    if not os.path.isdir(base_path):
        return []
    return sorted(
        [
            entry
            for entry in os.listdir(base_path)
            if os.path.isdir(os.path.join(base_path, entry))
            and not entry.startswith(".")
        ]
    )


def list_instances(base_path: str = "/opt/odoo") -> list[str]:
    return list_dirs(base_path)


def read_odoo_conf(conf_path: str) -> dict[str, str]:
    values: dict[str, str] = {}
    if not os.path.exists(conf_path):
        return values

    with open(conf_path, encoding="utf-8") as file_handle:
        for raw_line in file_handle:
            line = raw_line.strip()
            if (
                not line
                or line.startswith("#")
                or line.startswith(";")
                or line.startswith("[")
            ):
                continue
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()

    return values


def detect_cpu_count() -> int:
    """Detected CPU count via ``nproc``, falling back to 1 when unavailable."""
    result = run("nproc", check=False)
    value = result.stdout.strip()
    if result.returncode == 0 and value.isdigit() and int(value) >= 1:
        return int(value)
    return 1


def detect_total_ram_bytes() -> int | None:
    """Total RAM in bytes from ``/proc/meminfo`` (``MemTotal`` is in kB), or None."""
    try:
        with open("/proc/meminfo", encoding="utf-8") as file_handle:
            for line in file_handle:
                if line.startswith("MemTotal:"):
                    parts = line.split()
                    if len(parts) >= 2 and parts[1].isdigit():
                        return int(parts[1]) * 1024
    except OSError:
        return None
    return None


def wkhtmltopdf_version() -> str | None:
    """Installed wkhtmltopdf version string (e.g. ``0.12.6``), or None if absent.

    The ``(with patched qt)`` suffix, when present, signals the Odoo-recommended
    build; callers may inspect the raw string for it.
    """
    if not command_ok("command -v wkhtmltopdf >/dev/null 2>&1"):
        return None
    result = run("wkhtmltopdf --version 2>/dev/null", check=False)
    text = result.stdout.strip() or result.stderr.strip()
    return text or None


def detect_os_release() -> dict[str, str]:
    """Parse ``/etc/os-release`` into a dict (e.g. ``ID``, ``VERSION_CODENAME``)."""
    values: dict[str, str] = {}
    try:
        with open("/etc/os-release", encoding="utf-8") as file_handle:
            for raw_line in file_handle:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
    except OSError:
        return values
    return values


def detect_nginx_version() -> tuple[int, int, int] | None:
    """Parse ``nginx -v`` (``nginx version: nginx/1.24.0``) into a version tuple."""
    if not command_ok("command -v nginx >/dev/null 2>&1"):
        return None
    # nginx prints its version banner to stderr.
    result = run("nginx -v 2>&1", check=False)
    match = re.search(r"nginx/(\d+)\.(\d+)\.(\d+)", result.stdout + result.stderr)
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def detect_postgres_version() -> int | None:
    """Detected local PostgreSQL server major version via ``SHOW server_version``."""
    result = run(
        'sudo -u postgres psql -tAc "SHOW server_version" 2>/dev/null',
        check=False,
    )
    match = re.search(r"(\d+)", result.stdout.strip())
    if result.returncode == 0 and match:
        return int(match.group(1))
    return None


def list_databases(
    db_host: str,
    db_port: int,
    db_user: str,
    db_password: str,
    owner: str = "",
) -> tuple[list[str], str | None]:
    """List non-template databases. When ``owner`` is a safe role name, the list is
    scoped to databases owned by that role or whose name starts with it — so managing
    an instance shows only its own databases, not every database on the server."""
    quoted_password = shlex.quote(db_password)
    quoted_host = shlex.quote(db_host)
    quoted_user = shlex.quote(db_user)
    if owner and re.fullmatch(r"[A-Za-z0-9_.-]{1,63}", owner):
        select = (
            "SELECT d.datname FROM pg_database d JOIN pg_roles r ON d.datdba = r.oid "
            "WHERE d.datistemplate = false "
            f"AND (r.rolname = '{owner}' OR d.datname LIKE '{owner}%') "
            "ORDER BY d.datname;"
        )
    else:
        select = "SELECT datname FROM pg_database WHERE datistemplate = false ORDER BY datname;"
    query_cmd = (
        f"PGPASSWORD={quoted_password} psql -h {quoted_host} -p {db_port} -U {quoted_user} "
        f'-d postgres -tA -c "{select}"'
    )
    result = run(query_cmd, check=False)
    if result.returncode != 0:
        error_text = (
            result.stderr.strip()
            or result.stdout.strip()
            or "Unknown error while listing databases."
        )
        return [], error_text

    rows = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return rows, None
