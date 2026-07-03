from __future__ import annotations

import getpass
import os
from pathlib import Path

from .ui import level_text, prompt_label, style, title

_last_selected_dir: Path | None = None


def _remember_directory_from_path(raw_path: str) -> None:
    global _last_selected_dir
    candidate = Path(raw_path).expanduser()
    candidate_dir = candidate if candidate.is_dir() else candidate.parent
    if candidate_dir.exists() and candidate_dir.is_dir():
        _last_selected_dir = candidate_dir.resolve()


def _path_has_allowed_extension(path: str, allowed_extensions: tuple[str, ...]) -> bool:
    normalized = path.strip().lower()
    return any(normalized.endswith(ext.lower()) for ext in allowed_extensions)


def _validate_selected_path_extension(
    selected_path: str,
    requested_label: str | None,
    allowed_extensions: tuple[str, ...] | None,
) -> bool:
    if not allowed_extensions:
        return True

    if _path_has_allowed_extension(selected_path, allowed_extensions):
        return True

    expected = ", ".join(allowed_extensions)
    target = requested_label or "archivo"
    print(
        level_text(
            "WARN",
            f"La ruta seleccionada para {target} no coincide con extensiones esperadas: {expected}",
        )
    )
    return ask_bool("¿Usar igualmente este archivo?", False)


def ask_text(label: str, default: str | None = None, required: bool = False) -> str:
    while True:
        suffix = f" [{default}]" if default is not None else ""
        value = input(f"{prompt_label(label)}{suffix}: ").strip()
        if value:
            return value
        if default is not None:
            return default
        if not required:
            return ""
        print(level_text("ERROR", "Valor obligatorio."))


def ask_int(label: str, default: int, min_value: int = 1, max_value: int = 65535) -> int:
    while True:
        raw = ask_text(label, str(default), required=True)
        try:
            value = int(raw)
        except ValueError:
            print(level_text("ERROR", "Debe ser un número entero."))
            continue
        if min_value <= value <= max_value:
            return value
        print(level_text("ERROR", f"Valor fuera de rango ({min_value}-{max_value})."))


def ask_port(label: str, default: int) -> int:
    return ask_int(label, default, min_value=1, max_value=65535)


def ask_secret(label: str, required: bool = True) -> str:
    """Prompt for a secret without echoing it to the screen (via getpass)."""
    while True:
        value = getpass.getpass(f"{prompt_label(label)}: ").strip()
        if value:
            return value
        if not required:
            return ""
        print(level_text("ERROR", "Valor obligatorio."))


def ask_bool(label: str, default: bool = True) -> bool:
    marker = "Y/n" if default else "y/N"
    affirmative = {"y", "yes", "s", "si", "sí"}
    negative = {"n", "no"}
    while True:
        raw = input(f"{prompt_label(label)} ({style(marker, 'dim')}): ").strip().lower()
        if not raw:
            return default
        if raw in affirmative:
            return True
        if raw in negative:
            return False
        print(level_text("ERROR", "Responde 'sí'/'s' o 'no'/'n' (Enter = opción por defecto)."))


def choose(label: str, options: list[str], default_index: int | None = None) -> str:
    """Render a numbered menu with a consistent ``0)`` cancel entry.

    If ``options`` already contains a cancel-like entry (``Cancelar``/``Volver``/
    ``Salir``), that is the ``0`` option and selecting it returns that string.
    Otherwise a synthetic ``0) Cancelar`` is shown and selecting it (or pressing
    Enter with no default) returns ``""`` — the sentinel every caller treats as
    "cancelled".
    """
    print(title(label))
    zero_candidates = ["Cancelar", "Volver", "Salir"]
    zero_option = next((item for item in zero_candidates if item in options), None)
    zero_label = zero_option if zero_option is not None else "Cancelar"

    indexed_options = [option for option in options if option != zero_option]

    print(f"  {style('0)', 'blue', 'bold')} {zero_label}")

    for index, option in enumerate(indexed_options, start=1):
        default_tag = (
            " (default)"
            if default_index is not None and options[default_index] == option
            else ""
        )
        marker = style(f"{index})", "blue", "bold")
        print(f"  {marker} {option}{style(default_tag, 'dim')}")

    while True:
        raw = input(f"{prompt_label('Selecciona opción')}: ").strip()
        if raw == "0":
            return zero_option if zero_option is not None else ""

        if not raw:
            if default_index is not None:
                return options[default_index]
            print(level_text("INFO", "Sin selección (0 para cancelar)."))
            return ""
        try:
            selected = int(raw)
        except ValueError:
            print(level_text("ERROR", "Introduce el número de opción."))
            continue
        if 1 <= selected <= len(indexed_options):
            return indexed_options[selected - 1]
        print(level_text("ERROR", "Opción fuera de rango."))


def select_file_path(
    start_dir: str = ".",
    requested_label: str | None = None,
    allowed_extensions: tuple[str, ...] | None = None,
) -> str:
    if _last_selected_dir and _last_selected_dir.is_dir():
        current = _last_selected_dir
    else:
        current = Path(start_dir).expanduser().resolve()

    while True:
        if requested_label:
            print(f"\n{title('Seleccionar archivo requerido')}: {requested_label}")
        print(f"{title('Directorio actual')}: {current}")
        if _last_selected_dir and _last_selected_dir.is_dir():
            print(level_text("INFO", f"Última carpeta usada: {_last_selected_dir}"))
        entries = sorted(
            current.iterdir(), key=lambda item: (item.is_file(), item.name.lower())
        )
        print("  0) Elegir este directorio")
        print("  ..) Subir nivel")
        print("  q) Cancelar")
        for index, entry in enumerate(entries, start=1):
            marker = "/" if entry.is_dir() else ""
            print(f"  {index}) {entry.name}{marker}")

        raw = input(f"{prompt_label("Elige número, '..', 'q' o ruta manual")}: ").strip()
        if raw.lower() in {"q", "cancelar"}:
            return ""
        if raw == "0":
            manual = input(
                f"{prompt_label('Nombre de archivo en este directorio (o Enter para ruta manual)')}: "
            ).strip()
            if manual:
                candidate = current / manual
                candidate_text = str(candidate)
                if _validate_selected_path_extension(
                    candidate_text, requested_label, allowed_extensions
                ):
                    _remember_directory_from_path(candidate_text)
                    return candidate_text
                continue
            manual_path = input(f"{prompt_label('Ruta completa del archivo')}: ").strip()
            if manual_path:
                resolved = str(Path(manual_path).expanduser())
                if _validate_selected_path_extension(
                    resolved, requested_label, allowed_extensions
                ):
                    _remember_directory_from_path(resolved)
                    return resolved
            continue
        if raw == "..":
            current = current.parent
            continue

        if raw.isdigit():
            idx = int(raw)
            if 1 <= idx <= len(entries):
                selected = entries[idx - 1]
                if selected.is_dir():
                    current = selected
                else:
                    selected_text = str(selected)
                    if _validate_selected_path_extension(
                        selected_text, requested_label, allowed_extensions
                    ):
                        _remember_directory_from_path(selected_text)
                        return selected_text
                continue

        if raw:
            resolved = str(Path(raw).expanduser())
            if _validate_selected_path_extension(
                resolved, requested_label, allowed_extensions
            ):
                _remember_directory_from_path(resolved)
                return resolved
            continue

        print(level_text("ERROR", "Entrada no válida."))


def clear_screen() -> None:
    command = "cls" if os.name == "nt" else "clear"
    os.system(command)


def confirm_with_phrase(label: str, phrase: str) -> bool:
    print(title(label))
    value = input(
        f"{prompt_label('Escribe exactamente')} {style(phrase, 'magenta', 'bold')} {prompt_label('para confirmar')}: "
    ).strip()
    return value == phrase
