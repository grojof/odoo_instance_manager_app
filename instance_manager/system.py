from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass

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
        raise RuntimeError("Para aplicar cambios en sistema ejecuta como root (sudo).")


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
    print(f"\n{title('Plan de ejecución')}")
    indent = "     "
    body_width = max(20, shutil.get_terminal_size((100, 24)).columns - len(indent))
    for index, item in enumerate(commands, start=1):
        print(f"\n{style(f'[{index:02d}]', 'blue', 'bold')} {item.description}")
        for chunk in wrap_plain_block(item.command, body_width):
            print(style(f"{indent}{chunk}", "dim"))


def apply_commands(commands: list[Command], stop_on_error: bool = True) -> None:
    for index, item in enumerate(commands, start=1):
        print(f"\n{style(f'[{index}/{len(commands)}]', 'blue', 'bold')} {item.description}")
        # Stream output live so long steps (apt/pip/pg_restore) aren't silent.
        result = run_streaming(item.command)
        if result.returncode != 0:
            print(level_text("ERROR", f"Comando terminó con código {result.returncode}."))
            if stop_on_error:
                raise RuntimeError(f"Fallo ejecutando: {item.command}")


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


def list_databases(
    db_host: str,
    db_port: int,
    db_user: str,
    db_password: str,
) -> tuple[list[str], str | None]:
    quoted_password = shlex.quote(db_password)
    quoted_host = shlex.quote(db_host)
    quoted_user = shlex.quote(db_user)
    query_cmd = (
        f"PGPASSWORD={quoted_password} psql -h {quoted_host} -p {db_port} -U {quoted_user} "
        '-d postgres -tA -c "SELECT datname FROM pg_database WHERE datistemplate = false ORDER BY datname;"'
    )
    result = run(query_cmd, check=False)
    if result.returncode != 0:
        error_text = (
            result.stderr.strip()
            or result.stdout.strip()
            or "Error desconocido al listar bases de datos."
        )
        return [], error_text

    rows = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return rows, None
