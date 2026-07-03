"""Configure and query system logrotate for an instance's Odoo log."""

from __future__ import annotations

from ..models import InstanceConfig
from ..planners import plan_logrotate_config
from ..prompts import ask_bool, ask_int, ask_text, choose
from ..system import path_exists, read_odoo_conf, run
from ..ui import level_text, render_table, title
from .common import _execute_plan, _quote, _read_text_file


def _nginx_logs_covered_by_system() -> bool:
    """True if the distribution's `/etc/logrotate.d/nginx` already rotates the
    per-instance Nginx logs (its standard `/var/log/nginx/*.log` glob covers them)."""
    content = _read_text_file("/etc/logrotate.d/nginx")
    if not content:
        return False
    return "/var/log/nginx/*.log" in content or "/var/log/nginx/*" in content


def _query_log_rotation(config: InstanceConfig) -> None:
    lr_file = config.logrotate_config_file
    lr_present = path_exists(lr_file)
    policy_content = _read_text_file(lr_file) if lr_present else ""
    odoo_active = lr_present and config.odoo_log_file in policy_content
    conf_values = read_odoo_conf(config.odoo_conf_file)
    obsolete_key = "logrotate" in conf_values

    print(f"\n{title('Rotación de logs de la instancia')}")
    rows = [
        ["Log de Odoo", config.odoo_log_file],
        [
            "Rotación log Odoo",
            level_text("OK", "ACTIVA (system logrotate)")
            if odoo_active
            else level_text("MISSING", "INACTIVA"),
        ],
        ["Política logrotate.d", lr_file if lr_present else f"{lr_file} (no configurada)"],
    ]
    print(render_table(["Elemento", "Valor"], rows))

    if lr_present:
        print(f"\n{title('Política logrotate actual')}")
        print(policy_content.strip() or "(vacío)")
        print(f"\n{title('Previsualización (logrotate -d)')}")
        dry = run(f"logrotate -d {_quote(lr_file)}", check=False)
        print((dry.stdout or dry.stderr).strip() or "(sin salida)")
    else:
        print(level_text("INFO", "No hay política de logrotate del sistema para esta instancia."))

    print(f"\n{title('Ficheros de log de Odoo')}")
    sizes = run(f"ls -lh {_quote(config.odoo_log_file)}* 2>/dev/null", check=False)
    print(sizes.stdout.strip() or "(sin ficheros de log)")

    if _nginx_logs_covered_by_system():
        print(level_text("INFO", "Logs de Nginx: rotados por el logrotate del sistema (/etc/logrotate.d/nginx)."))
    elif config.nginx_access_log in policy_content:
        print(level_text("OK", "Logs de Nginx: rotados por esta política (create + reopen SIGUSR1)."))
    else:
        print(
            level_text(
                "WARN",
                "Logs de Nginx: sin cobertura de rotación detectada; considera incluirlos al configurar.",
            )
        )
    if obsolete_key:
        print(
            level_text(
                "INFO",
                "El odoo.conf contiene la clave 'logrotate' (obsoleta desde Odoo 13, ignorada); "
                "puedes limpiarla al configurar.",
            )
        )


def _configure_log_rotation(config: InstanceConfig) -> None:
    print(f"\n{title('Configurar rotación de logs (system logrotate)')}")
    frequency = choose(
        "Frecuencia de rotación",
        ["weekly", "daily", "monthly"],
        default_index=0,
    )
    if not frequency:
        return
    rotate_count = ask_int(
        "Número de rotaciones a conservar", 14, min_value=1, max_value=365
    )
    compress = ask_bool("¿Comprimir logs rotados?", True)
    maxsize = ""
    if ask_bool("¿Rotar también al superar un tamaño?", False):
        maxsize = ask_text("Tamaño máximo (p. ej. 50M, 1G)", "50M", required=True)

    conf_values = read_odoo_conf(config.odoo_conf_file)
    remove_obsolete = False
    if "logrotate" in conf_values:
        print(
            level_text(
                "INFO",
                "El odoo.conf tiene la clave 'logrotate' (obsoleta desde Odoo 13; Odoo la ignora).",
            )
        )
        remove_obsolete = ask_bool("¿Eliminarla del odoo.conf?", True)

    include_nginx = False
    if _nginx_logs_covered_by_system():
        print(
            level_text(
                "INFO",
                "Los logs de Nginx ya los cubre el logrotate del sistema "
                "(/etc/logrotate.d/nginx); no se añaden aquí para evitar doble rotación.",
            )
        )
    else:
        print(
            level_text(
                "WARN",
                "El logrotate del sistema no cubre los logs de Nginx de la instancia.",
            )
        )
        include_nginx = ask_bool(
            "¿Incluir también los logs de Nginx de la instancia (create + reopen SIGUSR1)?",
            True,
        )

    commands = plan_logrotate_config(
        config,
        frequency=frequency,
        rotate_count=rotate_count,
        compress=compress,
        maxsize=maxsize,
        remove_obsolete_odoo_key=remove_obsolete,
        include_nginx=include_nginx,
    )
    _execute_plan(commands)


def manage_log_rotation(config: InstanceConfig) -> None:
    while True:
        action = choose(
            f"Rotación de logs: {config.instance}",
            [
                "Consultar rotación actual",
                "Configurar rotación (system logrotate)",
                "Volver",
            ],
            default_index=None,
        )
        if action in {"", "Volver"}:
            return
        if action == "Consultar rotación actual":
            _query_log_rotation(config)
        elif action == "Configurar rotación (system logrotate)":
            _configure_log_rotation(config)
