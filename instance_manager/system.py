from __future__ import annotations

import configparser
import os
import platform
import re
import shlex
import shutil
import signal
import subprocess
from dataclasses import dataclass, field

from .i18n import t, tf
from .ui import level_text, sanitize, style, title, wrap_plain_block


@dataclass
class Command:
    """One plan step. ``env`` carries what must not be in the command text —
    passwords, file contents holding secrets — into the step's environment, which
    only root can read (``/proc/<pid>/environ``), unlike a process's arguments,
    which every local user sees in ``ps``. ``display`` is what the preview shows
    instead of ``command`` when the step was written for it (secrets masked)."""

    description: str
    command: str
    env: dict[str, str] = field(default_factory=dict)
    display: str = ""

    @property
    def shown(self) -> str:
        return self.display or self.command


# A remote PostgreSQL that drops packets would otherwise hold a probe (and the
# menu) until the TCP connect gives up, minutes later.
PG_CONNECT_TIMEOUT = "10"


def pg_env(password: str) -> dict[str, str]:
    """The environment a libpq client takes its password from: never its argv."""
    return {"PGPASSWORD": password or "", "PGCONNECT_TIMEOUT": PG_CONNECT_TIMEOUT}


def mask(text: str, secrets: tuple[str, ...] | list[str]) -> str:
    """``text`` with every non-empty secret replaced by ``********``, also where it
    appears escaped: inside an SQL literal (``'`` doubled) or a shell word."""
    forms = {form for s in secrets if s for form in (s, s.replace("'", "''"), shlex.quote(s))}
    for secret in sorted(forms, key=len, reverse=True):
        text = text.replace(secret, "********")
    return text


def _environment(env: dict[str, str] | None) -> dict[str, str] | None:
    return {**os.environ, **env} if env else None


def run(
    command: str, check: bool = False, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["bash", "-lc", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=_environment(env),
    )
    if check and result.returncode != 0:
        # Not the command: it may hold what a preview masks.
        raise RuntimeError(f"Command failed (exit {result.returncode}): {result.stderr.strip()}")
    return result


def _stop_group(process: subprocess.Popen[str]) -> None:
    """TERM the step's process group (a staged write restores on it), then KILL it
    if it has not ended after 10 seconds."""
    for sig, wait in ((signal.SIGTERM, 10), (signal.SIGKILL, 5)):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=wait)
            return
        except subprocess.TimeoutExpired:
            continue


def run_streaming(command: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Run a command, forwarding its output live while also capturing it.

    stdlib-only (``subprocess.Popen``): stderr is merged into stdout so combined
    output appears in real time — useful for long steps (apt/pip/pg_restore) that
    would otherwise sit silent. stdin is closed so a command never blocks waiting
    for input. Returns a ``CompletedProcess`` with the accumulated output.
    """
    # Its own process group, so Ctrl+C here stops the whole step (bash and what it
    # started), and waits for it: a step left running behind the menu could still
    # be writing when the next plan starts.
    process = subprocess.Popen(
        ["bash", "-lc", command],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=_environment(env),
        start_new_session=True,
    )
    captured: list[str] = []
    assert process.stdout is not None
    try:
        for line in process.stdout:
            print(sanitize(line, keep_cr=True), end="", flush=True)
            captured.append(line)
    except KeyboardInterrupt:
        _stop_group(process)
        raise
    process.stdout.close()
    returncode = process.wait()
    return subprocess.CompletedProcess(process.args, returncode, "".join(captured), "")


def require_root_for_apply() -> None:
    if os.geteuid() != 0:
        raise RuntimeError('To apply system changes, run as root (sudo).')


def command_ok(command: str) -> bool:
    return run(command, check=False).returncode == 0


# Probes run before any plan is previewed, so every value they take is quoted here
# rather than trusted to have been validated by the caller.


def user_exists(username: str) -> bool:
    return command_ok(f"id -u -- {shlex.quote(username)} >/dev/null 2>&1")


def service_exists(service_name: str) -> bool:
    return command_ok(f"systemctl cat -- {shlex.quote(service_name)} >/dev/null 2>&1")


def service_active(service_name: str) -> bool:
    return command_ok(f"systemctl is-active --quiet -- {shlex.quote(service_name)}")


def service_enabled(service_name: str) -> bool:
    return command_ok(f"systemctl is-enabled --quiet -- {shlex.quote(service_name)}")


def path_exists(path: str) -> bool:
    return command_ok(f"test -e {shlex.quote(path)}")


def sql_literal(value: str) -> str:
    """``value`` as a quoted SQL string literal."""
    return "'" + (value or "").replace("'", "''") + "'"


def _local_psql_value(sql: str) -> str | None:
    """The single value ``sql`` returns on the local server, as postgres; None when
    the query cannot run."""
    result = run(f"sudo -u postgres psql -X -tA -d postgres -c {shlex.quote(sql)}", check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def db_role_exists(role_name: str) -> bool:
    return _local_psql_value(f"SELECT 1 FROM pg_roles WHERE rolname = {sql_literal(role_name)}") == "1"


def db_role_absent(role_name: str) -> bool:
    """True only when the role certainly does not exist yet: the local server says
    so, or there is no local PostgreSQL at all. A role an install may drop on failure
    must be one it created, so "cannot tell" is False."""
    if not user_exists("postgres"):
        return True
    return _local_psql_value(f"SELECT 1 FROM pg_roles WHERE rolname = {sql_literal(role_name)}") == ""


def database_exists(db_name: str) -> bool:
    return _local_psql_value(f"SELECT 1 FROM pg_database WHERE datname = {sql_literal(db_name)}") == "1"


def database_comment(db_name: str) -> str:
    """The comment on ``db_name`` on the local server ("" when none or unreadable)."""
    return _local_psql_value(
        "SELECT coalesce(shobj_description(oid, 'pg_database'), '') FROM pg_database "
        f"WHERE datname = {sql_literal(db_name)}"
    ) or ""


def local_postgres_available() -> bool:
    """True when the local server answers as postgres (``sudo -u postgres``)."""
    return _local_psql_value("SELECT 1") == "1"


def database_owner(db_name: str) -> str | None:
    """The role owning ``db_name`` on the local server, or None when it does not
    exist (or the server cannot be queried)."""
    owner = _local_psql_value(
        "SELECT r.rolname FROM pg_database d JOIN pg_roles r ON r.oid = d.datdba "
        f"WHERE d.datname = {sql_literal(db_name)}"
    )
    return owner or None


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
        print(f"\n{style(f'[{index:02d}]', 'blue', 'bold')} {sanitize(t(item.description))}")
        for chunk in wrap_plain_block(sanitize(item.shown), body_width):
            print(style(f"{indent}{chunk}", "dim"))


def apply_commands(commands: list[Command], stop_on_error: bool = True) -> None:
    for index, item in enumerate(commands, start=1):
        print(f"\n{style(f'[{index}/{len(commands)}]', 'blue', 'bold')} {sanitize(t(item.description))}")
        # Stream output live so long steps (apt/pip/pg_restore) aren't silent.
        result = run_streaming(item.command, item.env)
        if result.returncode != 0:
            print(level_text("ERROR", tf('Command finished with code {}.', result.returncode)))
            if stop_on_error:
                # The description, not the command: the command may hold what the
                # preview masked.
                raise RuntimeError(tf('Failed running: {}', t(item.description)))


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


def _conf_text(conf_path: str) -> str:
    try:
        with open(conf_path, encoding="utf-8", errors="replace") as file_handle:
            return file_handle.read()
    except OSError:
        return ""


def read_odoo_conf(conf_path: str) -> dict[str, str]:
    """The ``[options]`` of an odoo.conf as Odoo reads it (``RawConfigParser``: keys
    lower-cased, a continued value kept whole with its newlines). A file with no
    section header is read line by line, as before."""
    text = _conf_text(conf_path)
    if not text:
        return {}
    parser = configparser.RawConfigParser(strict=False, interpolation=None)
    try:
        parser.read_string(text)
    except configparser.MissingSectionHeaderError:
        values: dict[str, str] = {}
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if line and not line.startswith(("#", ";", "[")) and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip().lower()] = value.strip()
        return values
    except configparser.Error:
        return {}
    return dict(parser["options"]) if parser.has_section("options") else {}


def read_conf_other_sections(conf_path: str) -> str:
    """The text of every section of an odoo.conf other than ``[options]`` (a
    module's own settings, such as ``[queue_job]``), as written."""
    kept: list[str] = []
    section = ""
    for line in _conf_text(conf_path).splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1].strip().lower()
        if section and section != "options":
            kept.append(line)
    return "\n".join(kept).strip("\n")


def detect_host_python() -> str | None:
    """The host python3's ``major.minor`` (e.g. ``3.12``), or None when absent."""
    result = run('python3 -c "import sys; print(\'%d.%d\' % sys.version_info[:2])"', check=False)
    value = result.stdout.strip()
    return value if result.returncode == 0 and re.fullmatch(r"3\.\d{1,2}", value) else None


def detect_arch() -> str:
    """The machine architecture as uv names its assets (``x86_64``, ``aarch64``)."""
    return platform.machine()


def detect_ssh_ports() -> list[int]:
    """The ports SSH listens on: sshd's effective ``Port`` (``sshd -T``) and, on
    socket-activated hosts (Ubuntu 24.04's ``ssh.socket``), the socket's
    ``ListenStream``. Empty when neither can be read."""
    ports: list[int] = []
    result = run("sshd -T 2>/dev/null", check=False)
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] == "port" and parts[1].isdigit():
            ports.append(int(parts[1]))
    result = run("systemctl show -p Listen ssh.socket 2>/dev/null", check=False)
    for match in re.finditer(r"[:\]](\d{1,5}) \(Stream\)", result.stdout):
        ports.append(int(match.group(1)))
    return sorted(set(port for port in ports if 1 <= port <= 65535))


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


def apt_candidate(package: str) -> str:
    """The version apt would install for ``package`` ("" when it has none)."""
    result = run(f"apt-cache policy {shlex.quote(package)} 2>/dev/null", check=False)
    match = re.search(r"Candidate:\s*(\S+)", result.stdout)
    return "" if not match or match.group(1) == "(none)" else match.group(1)


def detect_nginx_version() -> tuple[int, int, int] | None:
    """The nginx a vhost is written for: the installed one (``nginx -v`` prints
    ``nginx version: nginx/1.24.0``), else the one apt would install — a plan that
    installs nginx is built before it is there. None when neither is known."""
    if command_ok("command -v nginx >/dev/null 2>&1"):
        # nginx prints its version banner to stderr.
        result = run("nginx -v 2>&1", check=False)
        match = re.search(r"nginx/(\d+)\.(\d+)\.(\d+)", result.stdout + result.stderr)
    else:
        match = re.match(r"(?:\d+:)?(\d+)\.(\d+)\.(\d+)", apt_candidate("nginx"))
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def list_databases(
    db_host: str,
    db_port: int,
    db_user: str,
    db_password: str,
    owner: str = "",
) -> tuple[list[str], str | None]:
    """List non-template databases. When ``owner`` is a safe role name, the list is
    scoped to databases owned by that role or named exactly like it — so managing an
    instance shows only its own databases. A name prefix is not used: instance
    ``shop`` would otherwise list ``shop2`` and ``shop_eu``, and ``_`` is a LIKE
    wildcard."""
    quoted_host = shlex.quote(db_host)
    quoted_user = shlex.quote(db_user)
    if owner and re.fullmatch(r"[A-Za-z0-9_.-]{1,63}", owner):
        select = (
            "SELECT d.datname FROM pg_database d JOIN pg_roles r ON d.datdba = r.oid "
            "WHERE d.datistemplate = false "
            f"AND (r.rolname = {sql_literal(owner)} OR d.datname = {sql_literal(owner)}) "
            "ORDER BY d.datname;"
        )
    else:
        select = "SELECT datname FROM pg_database WHERE datistemplate = false ORDER BY datname;"
    query_cmd = (
        f"psql -X -h {quoted_host} -p {int(db_port)} -U {quoted_user} "
        f"-d postgres -tA -c {shlex.quote(select)}"
    )
    result = run(query_cmd, check=False, env=pg_env(db_password))
    if result.returncode != 0:
        error_text = (
            result.stderr.strip()
            or result.stdout.strip()
            or "Unknown error while listing databases."
        )
        return [], error_text

    rows = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return rows, None
