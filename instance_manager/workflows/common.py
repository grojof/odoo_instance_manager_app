"""Shared low-level helpers used across the workflow capability modules.

Everything here depends only on the lower layers (``models``, ``system``,
``prompts``, ``ui``) and on other helpers in this module — never on a feature
module — so importing it never creates a cycle.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass

from ..models import InstanceConfig
from ..prompts import ask_bool, ask_int, ask_secret, ask_text, choose
from ..system import (
    Command,
    apply_commands,
    list_databases,
    list_instances,
    path_exists,
    preview_commands,
    read_odoo_conf,
    require_root_for_apply,
    run,
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


def _execute_plan(commands: list[Command]) -> None:
    if not commands:
        print(level_text("INFO", "No hay acciones para ejecutar."))
        return

    preview_commands(commands)
    mode = choose(
        "Confirmar acción",
        ["Cancelar", "Confirmar plan y ejecutar"],
        default_index=None,
    )
    if mode in {"", "Cancelar"}:
        return
    require_root_for_apply()
    apply_commands(commands)
    print(f"\n{level_text('OK', 'Plan ejecutado correctamente.')}")


def _collect_db_connection(instance: str) -> tuple[str, int, str, str] | None:
    wants_db_query = ask_bool(
        "¿Quieres conectarte a PostgreSQL para listar DBs disponibles?",
        False,
    )
    if not wants_db_query:
        return None

    db_host = ask_text("DB server", "127.0.0.1", required=True)
    db_port = ask_int("DB port", 5432)
    db_user = ask_text("DB user", instance, required=True)
    db_password = ask_secret("DB password")
    return db_host, db_port, db_user, db_password


def _list_detected_instances(base_dir: str) -> list[str]:
    instances = list_instances(base_dir)
    print(f"\nInstancias detectadas en {base_dir}:")
    if not instances:
        print("  No se detectaron carpetas de instancia en el directorio base.")
        print("  Puedes escribir el nombre de una instancia conocida")
        print("  para eliminar otros datos residuales como configs, servicios, logs, etc.")
    for item in instances:
        print(f"- {item}")
    return instances


def _select_existing_instance() -> str:
    base_dir = InstanceConfig.base_instances_dir
    instances = _list_detected_instances(base_dir)

    if instances:
        selected = choose(
            "Selecciona instancia detectada",
            instances + ["Escribir nombre", "Cancelar"],
            default_index=None,
        )
        if selected == "Cancelar" or selected == "":
            return ""
        if selected != "Escribir nombre":
            return selected

    return ask_text("Nombre de instancia", "", required=False)


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


def _is_safe_path_component(name: str) -> bool:
    """True if ``name`` is safe to embed as a single filesystem path component.

    Guards against path traversal when an operator-entered database name is
    interpolated into a filestore path that is created, archived, or deleted.
    """
    return (
        bool(name)
        and "/" not in name
        and "\\" not in name
        and "\x00" not in name
        and name not in {".", ".."}
        and not name.startswith(".")
    )


def _probe_databases_for_management(instance: str) -> tuple[str, str | None, list[str]]:
    db_name = ""
    db_error: str | None = None
    listed_dbs: list[str] = []

    db_connection = _collect_db_connection(instance)
    if db_connection:
        db_host, db_port, db_user, db_password = db_connection
        listed_dbs, db_error = list_databases(db_host, db_port, db_user, db_password)
        if db_error:
            print(f"[WARN] Fallo al consultar DBs: {db_error}")
        elif listed_dbs:
            print("\nDBs disponibles:")
            for item in listed_dbs:
                print(f"- {item}")
            selected = choose(
                "Selecciona DB para validaciones (opcional)",
                listed_dbs + ["No seleccionar"],
                default_index=None,
            )
            if selected and selected != "No seleccionar":
                db_name = selected
        else:
            print("[INFO] Conexión a DB exitosa, sin bases listadas.")

    if not db_name:
        db_name = ask_text("DB para validaciones (opcional)", "", required=False)

    return db_name, db_error, listed_dbs


def _resolve_data_dir(config: InstanceConfig) -> str:
    values = read_odoo_conf(config.odoo_conf_file)
    data_dir = values.get("data_dir", "").strip()
    if data_dir:
        return data_dir
    return f"{config.odoo_home}/.local/share/Odoo"


def _filestore_path(config: InstanceConfig, db_name: str) -> str:
    data_dir = _resolve_data_dir(config)
    return f"{data_dir}/filestore/{db_name}"


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
        f"¿Usar credenciales DB anteriores ({cached.user}@{cached.host}:{cached.port})?",
        True,
    ):
        return cached
    host = ask_text("DB server", cached.host if cached else "127.0.0.1", required=True)
    port = ask_int("DB port", cached.port if cached else 5432)
    user = ask_text("DB user", cached.user if cached else default_user, required=True)
    password = ask_secret("DB password")
    return DbCredentials(host, port, user, password)


def _pick_db_name(creds: DbCredentials, label: str, required: bool = True) -> str:
    """List databases with ``creds`` and let the operator pick one or type a name."""
    db_names, error = list_databases(creds.host, creds.port, creds.user, creds.password)
    if error:
        print(level_text("WARN", f"No se pudo listar DBs: {error}"))
    elif db_names:
        print("\nDBs disponibles:")
        for item in db_names:
            print(f"- {item}")
        pick = choose(
            f"{label} (selección rápida)",
            db_names + ["Escribir nombre manualmente"],
            default_index=None,
        )
        if pick and pick != "Escribir nombre manualmente":
            return pick
    else:
        print(level_text("INFO", "Conexión a DB exitosa, sin bases listadas."))
    return ask_text(label, "", required=required)


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
