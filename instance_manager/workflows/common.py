"""Shared low-level helpers used across the workflow capability modules.

Everything here depends only on the lower layers (``models``, ``system``,
``prompts``, ``ui``) and on other helpers in this module — never on a feature
module — so importing it never creates a cycle.
"""

from __future__ import annotations

import datetime
import os
import re
import shlex
from dataclasses import dataclass

from ..i18n import t, tf
from ..models import InstanceConfig
from ..prompts import ask_bool, ask_int, ask_secret, ask_text, choose
from ..system import (
    Command,
    apply_commands,
    list_databases,
    list_instances,
    path_exists,
    pg_env,
    preview_commands,
    read_odoo_conf,
    require_root_for_apply,
    run,
    service_exists,
    user_exists,
)
from ..ui import level_text


def _quote(value: str) -> str:
    return shlex.quote(value)


def _default_odoo_conf_path(instance: str) -> str:
    return f"/etc/odoo/{instance}/{instance}.conf"


def _legacy_odoo_conf_path(instance: str) -> str:
    return f"/etc/{instance}/odoo.conf"


def _odoo_conf_candidates(instance: str) -> list[str]:
    return [_default_odoo_conf_path(instance), _legacy_odoo_conf_path(instance)]


def _command_output(command: str) -> str:
    result = run(command, check=False)
    if result.returncode != 0:
        return ""
    return (result.stdout or result.stderr).strip()


def _read_text_file(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as file_handle:
            return file_handle.read()
    except OSError:
        return ""


def _confirm_plan(commands: list[Command]) -> bool:
    """Show the plan and ask for confirmation; True only on an explicit yes. Nothing
    runs here, so an interruption at this prompt has changed nothing."""
    if not commands:
        print(level_text("INFO", 'There are no actions to run.'))
        return False
    preview_commands(commands)
    mode = choose(
        'Confirm action',
        ['Cancel', 'Confirm plan and run'],
        default_index=None,
    )
    return mode == 'Confirm plan and run'


def _execute_plan(commands: list[Command]) -> None:
    if not _confirm_plan(commands):
        return
    require_root_for_apply()
    apply_commands(commands)
    print(f"\n{level_text('OK', 'Plan executed successfully.')}")


def _collect_db_connection(instance: str) -> tuple[str, int, str, str] | None:
    wants_db_query = ask_bool(
        'Connect to PostgreSQL to list available databases?',
        False,
    )
    if not wants_db_query:
        return None

    db_host = ask_text('DB server', "127.0.0.1", required=True)
    db_port = ask_int('DB port', 5432)
    db_user = ask_text('DB user', instance, required=True)
    db_password = ask_secret('DB password')
    return db_host, db_port, db_user, db_password


def _list_detected_instances(base_dir: str) -> list[str]:
    instances = list_instances(base_dir)
    print(tf('\nInstances detected in {}:', base_dir))
    if not instances:
        print(t('  No instance folders were detected in the base directory.'))
        print(t('  You can type the name of a known instance'))
        print(t('  to remove other residual data such as configs, services, logs, etc.'))
    for item in instances:
        print(f"- {item}")
    return instances


def _select_existing_instance() -> str:
    base_dir = InstanceConfig.base_instances_dir
    instances = _list_detected_instances(base_dir)

    if instances:
        selected = choose(
            'Select a detected instance',
            instances + ['Type a name', 'Cancel'],
            default_index=None,
        )
        if selected == 'Cancel' or selected == "":
            return ""
        if selected != 'Type a name':
            return selected

    return ask_text('Instance name', "", required=False)


def _validate_instance_or_abort(instance: str) -> InstanceConfig | None:
    """Build and validate a config for a destructive flow.

    Returns a normalized, validated ``InstanceConfig`` or ``None`` when the
    instance identifier is unsafe (printing a descriptive error). Callers must
    treat ``None`` as "abort back to the menu" and never build a plan from an
    unvalidated name.
    """
    config = InstanceConfig(instance=instance)
    config.normalize_defaults()
    try:
        config.validate_identifiers()
    except ValueError as error:
        print(level_text("ERROR", str(error)))
        return None
    return config


def _probe_databases_for_management(instance: str) -> tuple[str, str | None, list[str]]:
    db_name = ""
    db_error: str | None = None
    listed_dbs: list[str] = []

    db_connection = _collect_db_connection(instance)
    if db_connection:
        db_host, db_port, db_user, db_password = db_connection
        # Scope the listing to the instance's own role, not every database.
        listed_dbs, db_error = list_databases(db_host, db_port, db_user, db_password, owner=db_user)
        if db_error:
            print(tf('[WARN] Failed to query DBs: {}', db_error))
        elif listed_dbs:
            print(t('\nAvailable databases:'))
            for item in listed_dbs:
                print(f"- {item}")
            selected = choose(
                'Select a DB for validation (optional)',
                listed_dbs + ['Do not select'],
                default_index=None,
            )
            if selected and selected != 'Do not select':
                db_name = selected
        else:
            print(t('[INFO] DB connection successful, no databases listed.'))

    if not db_name:
        db_name = ask_text('DB for validation (optional)', "", required=False)

    return db_name, db_error, listed_dbs


_ADDONS_DIR_RE = re.compile(r"/[A-Za-z0-9/._-]{1,250}")


def _addons_paths(config: InstanceConfig) -> list[str]:
    """Where the instance's modules live: its odoo.conf ``addons_path`` plus the two
    directories Odoo itself always adds (``odoo/addons`` and ``addons`` of the
    checkout), each an absolute path of plain characters."""
    paths = [f"{config.odoo_home}/odoo/odoo/addons", f"{config.odoo_home}/odoo/addons"]
    for conf_path in _odoo_conf_candidates(config.instance):
        value = read_odoo_conf(conf_path).get("addons_path", "")
        if value:
            paths += [item.strip().rstrip("/") for item in value.split(",")]
            break
    return [p for p in dict.fromkeys(paths) if _ADDONS_DIR_RE.fullmatch(p) and ".." not in p.split("/")]


def _resolve_data_dir(config: InstanceConfig) -> str:
    """The instance's data dir: the one the config being built names (a new instance
    has no odoo.conf on disk yet), else ``data_dir`` from its odoo.conf (current or
    legacy location), else Odoo's default under the home."""
    if config.data_dir:
        return config.data_dir
    for conf_path in _odoo_conf_candidates(config.instance):
        data_dir = read_odoo_conf(conf_path).get("data_dir", "").strip()
        if data_dir:
            return data_dir
    return f"{config.odoo_home}/.local/share/Odoo"


def _data_dir_is_private(config: InstanceConfig, data_dir: str) -> bool:
    """True when ``data_dir`` can only be this instance's: the managed
    ``/var/lib/odoo/<instance>`` or a directory inside its home. A custom data dir
    elsewhere may be shared with other instances, so nothing is done to it as a whole."""
    return os.path.normpath(data_dir) == os.path.normpath(config.managed_data_dir) or _is_inside(
        data_dir, config.odoo_home
    )


def _own_filestore_commands(config: InstanceConfig, db_name: str) -> list[Command]:
    """Give a restored or copied filestore to the instance user. A private data dir is
    handed over whole (Odoo creates ``sessions`` and ``filestore`` in it); a data dir
    that may be shared gets only this database's filestore."""
    data_dir = _resolve_data_dir(config)
    owner = f"{_quote(config.odoo_user)}:{_quote(config.odoo_user)}"
    if _data_dir_is_private(config, data_dir):
        return [Command(
            'Own the data dir by the instance user (filestore, sessions, …)',
            f"chown -R {owner} {_quote(data_dir)}",
        )]
    return [Command(
        tf('Own the filestore of {} by the instance user', db_name),
        f"chown -R {owner} {_quote(_filestore_path(config, db_name))}",
    )]


# Directories a backup must not be written into directly: making them private
# (chmod 700) or pruning in them would affect everything else they hold.
_SHARED_DIRS = frozenset({
    "/", "/tmp", "/var", "/var/tmp", "/var/backups", "/var/lib", "/var/log", "/etc", "/usr",
    "/home", "/root", "/opt", "/opt/odoo", "/srv", "/mnt", "/media", "/boot", "/run", "/dev",
})


def _backup_dir_error(path: str) -> str | None:
    """An absolute, dedicated directory: the tool makes it private (700) and prunes
    in it, so a shared system directory is refused."""
    if not path.startswith("/") or "\n" in path or ".." in path.split("/"):
        return 'Use an absolute directory path.'
    if os.path.normpath(path) in _SHARED_DIRS:
        return tf('{} is a shared directory: use a dedicated one, such as /var/backups/<instance>.', path)
    return None


def _write_export(path: str, text: str) -> None:
    """Write a report the operator asked for, as root, without following a link: the
    file must be new (``O_EXCL``, which also refuses a link in its place) and is
    private (``600``) — reports name databases, users and paths."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as file_handle:
        file_handle.write(text)


def _existing_instance_artifacts(config: InstanceConfig) -> list[str]:
    """What already exists under this instance's names: an install must not take
    them over, and its cleanup could otherwise remove them."""
    found = []
    for label, present in (
        ('home', path_exists(config.odoo_home)),
        ('config', path_exists(config.odoo_conf_dir)),
        ('systemd unit', service_exists(config.odoo_service)),
        ('Nginx vhost', path_exists(f"/etc/nginx/sites-available/{config.nginx_http_name}")
         or path_exists(f"/etc/nginx/sites-available/{config.nginx_https_name}")),
        ('SSL directory', path_exists(config.nginx_ssl_dir)),
        ('Linux user', user_exists(config.odoo_user)),
    ):
        if present:
            found.append(label)
    return found


def _filestore_path(config: InstanceConfig, db_name: str) -> str:
    data_dir = _resolve_data_dir(config)
    return f"{data_dir}/filestore/{db_name}"


def _is_inside(path: str, directory: str) -> bool:
    """True if ``path`` is ``directory`` or lies under it (lexically, normalised)."""
    path_n, dir_n = os.path.normpath(path), os.path.normpath(directory)
    return path_n == dir_n or path_n.startswith(dir_n.rstrip("/") + "/")


def _kept_data_dir_path(config: InstanceConfig, timestamp: str) -> str:
    return f"/var/backups/{config.instance}/kept-data-dir-{timestamp}"


def _keep_data_dir_commands(
    config: InstanceConfig, data_dir: str, timestamp: str | None = None
) -> list[Command]:
    """Commands that move the instance's data dir out of its home before the home is
    removed, into a private directory under ``/var/backups/<instance>``. Nothing when
    the data dir lives elsewhere (``data_dir`` set outside the home)."""
    if not _is_inside(data_dir, config.odoo_home):
        return []
    ts = timestamp or datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    kept = _kept_data_dir_path(config, ts)
    parent = kept.rsplit("/", 1)[0]
    return [
        Command(
            tf('Keep the data dir (filestores) out of the home: move it to {}', kept),
            f"if [ -d {_quote(data_dir)} ]; then install -d -m 700 {_quote(parent)} && "
            f"mv -- {_quote(data_dir)} {_quote(kept)}; fi",
        )
    ]


@dataclass(frozen=True)
class DbCredentials:
    """PostgreSQL connection credentials reused across a management session."""

    host: str
    port: int
    user: str
    password: str


def _ask_db_credentials(
    default_user: str, cached: DbCredentials | None = None
) -> DbCredentials:
    """Collect DB credentials, offering to reuse the ones from earlier this session."""
    if cached is not None and ask_bool(
        tf('Reuse the previous DB credentials ({}@{}:{})?', cached.user, cached.host, cached.port),
        True,
    ):
        return cached
    host = ask_text('DB server', cached.host if cached else "127.0.0.1", required=True)
    port = ask_int('DB port', cached.port if cached else 5432)
    user = ask_text('DB user', cached.user if cached else default_user, required=True)
    password = ask_secret('DB password')
    return DbCredentials(host, port, user, password)


def _pick_db_name(creds: DbCredentials, label: str, required: bool = True) -> str:
    """List databases with ``creds`` (scoped to the connected role) and let the
    operator pick one or type a name."""
    db_names, error = list_databases(
        creds.host, creds.port, creds.user, creds.password, owner=creds.user
    )
    if error:
        print(level_text("WARN", tf('Could not list databases: {}', error)))
    elif db_names:
        print(t('\nAvailable databases:'))
        for item in db_names:
            print(f"- {item}")
        pick = choose(
            tf('{} (quick pick)', label),
            db_names + ['Type the name manually'],
            default_index=None,
        )
        if pick and pick != 'Type the name manually':
            return pick
    else:
        print(level_text("INFO", 'DB connection succeeded, no databases listed.'))
    return ask_text(label, "", required=required)


def _database_exists(creds: DbCredentials, db_name: str) -> bool:
    """Best-effort check that ``db_name`` exists using ``creds``.

    Returns False both when the database is absent and when the check cannot run
    (e.g. connection failure); callers treat both as "do not attempt the drop".
    """
    sql = "SELECT 1 FROM pg_database WHERE datname='" + db_name.replace("'", "''") + "'"
    cmd = (
        f"psql -X -h {shlex.quote(creds.host)} "
        f"-p {int(creds.port)} -U {shlex.quote(creds.user)} -d postgres -tAc {shlex.quote(sql)}"
    )
    result = run(cmd, check=False, env=pg_env(creds.password))
    return result.returncode == 0 and result.stdout.strip() == "1"


def _instance_db_user(config: InstanceConfig) -> str:
    for conf_path in _odoo_conf_candidates(config.instance):
        db_user = read_odoo_conf(conf_path).get("db_user", "").strip()
        if db_user:
            return db_user
    return config.db_user or config.instance


def _database_owner(creds: DbCredentials, db_name: str) -> str:
    """The role owning ``db_name``, or "" when it is absent or cannot be read."""
    sql = (
        "SELECT r.rolname FROM pg_database d JOIN pg_roles r ON r.oid = d.datdba "
        "WHERE d.datname = '" + db_name.replace("'", "''") + "'"
    )
    cmd = (
        f"psql -X -h {shlex.quote(creds.host)} -p {int(creds.port)} -U {shlex.quote(creds.user)} "
        f"-d postgres -tAc {shlex.quote(sql)}"
    )
    result = run(cmd, check=False, env=pg_env(creds.password))
    return result.stdout.strip() if result.returncode == 0 else ""


def _is_self_signed_certificate(cert_path: str) -> bool:
    if not cert_path or not path_exists(cert_path):
        return False

    result = run(
        f"openssl x509 -in {_quote(cert_path)} -noout -subject -issuer",
        check=False,
    )
    if result.returncode != 0:
        return False

    subject_line = ""
    issuer_line = ""
    for line in result.stdout.splitlines():
        normalized = line.strip()
        if normalized.startswith("subject="):
            subject_line = normalized[len("subject=") :].strip()
        elif normalized.startswith("issuer="):
            issuer_line = normalized[len("issuer=") :].strip()

    return bool(subject_line and issuer_line and subject_line == issuer_line)
