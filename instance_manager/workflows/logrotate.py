"""Configure and query system logrotate for an instance's Odoo log."""

from __future__ import annotations

from ..models import InstanceConfig
from ..planners import plan_logrotate_config
from ..prompts import ask_bool, ask_int, ask_text, choose
from ..system import path_exists, read_odoo_conf, run
from ..ui import level_text, render_table, title
from .common import _execute_plan, _quote


def _query_log_rotation(config: InstanceConfig) -> None:
    lr_file = config.logrotate_config_file
    lr_present = path_exists(lr_file)
    conf_values = read_odoo_conf(config.odoo_conf_file)
    odoo_flag = conf_values.get("logrotate", "(no definido)")

    print(f"\n{title('Rotación de logs de la instancia')}")
    rows = [
        ["Log de Odoo", config.odoo_log_file],
        ["logrotate.d (sistema)", lr_file if lr_present else f"{lr_file} (no configurado)"],
        ["Odoo logrotate (conf)", odoo_flag],
    ]
    print(render_table(["Elemento", "Valor"], rows))

    if lr_present:
        print(f"\n{title('Política logrotate actual')}")
        current = run(f"cat {_quote(lr_file)}", check=False)
        print(current.stdout.strip() or "(vacío)")
        print(f"\n{title('Previsualización (logrotate -d)')}")
        dry = run(f"logrotate -d {_quote(lr_file)}", check=False)
        print((dry.stdout or dry.stderr).strip() or "(sin salida)")
    else:
        print(level_text("INFO", "No hay política de logrotate del sistema para esta instancia."))

    print(f"\n{title('Ficheros de log de Odoo')}")
    sizes = run(f"ls -lh {_quote(config.odoo_log_file)}* 2>/dev/null", check=False)
    print(sizes.stdout.strip() or "(sin ficheros de log)")

    print(
        level_text(
            "INFO",
            "Los logs de Nginx (/var/log/nginx/<inst>.*.log) los rota el logrotate del sistema "
            "de Nginx (/etc/logrotate.d/nginx); esta utilidad gestiona el log de Odoo.",
        )
    )
    if odoo_flag.strip().lower() == "true" and lr_present:
        print(
            level_text(
                "WARN",
                "Odoo tiene logrotate=True y además hay logrotate del sistema: posible doble "
                "rotación. Considera desactivar el interno al configurar.",
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
    disable_odoo_internal = False
    if conf_values.get("logrotate", "").strip().lower() == "true":
        print(
            level_text(
                "WARN",
                "El odoo.conf tiene logrotate=True; con logrotate del sistema habría doble rotación.",
            )
        )
        disable_odoo_internal = ask_bool(
            "¿Poner logrotate=False en el odoo.conf? (requiere reiniciar Odoo)", True
        )

    commands = plan_logrotate_config(
        config,
        frequency=frequency,
        rotate_count=rotate_count,
        compress=compress,
        maxsize=maxsize,
        disable_odoo_internal=disable_odoo_internal,
    )
    _execute_plan(commands)
    if disable_odoo_internal:
        print(
            level_text(
                "INFO",
                "Reinicia el servicio Odoo para aplicar logrotate=False "
                "(menú 'Servicios instancias' → Reiniciar).",
            )
        )


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
