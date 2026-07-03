from __future__ import annotations

import getpass
import os
from pathlib import Path

from .i18n import current_language, t, tf
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
            tf('The selected path for {} does not match the expected extensions: {}', target, expected),
        )
    )
    return ask_bool('Use this file anyway?', False)


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
        print(level_text("ERROR", 'Value is required.'))


def ask_int(label: str, default: int, min_value: int = 1, max_value: int = 65535) -> int:
    while True:
        raw = ask_text(label, str(default), required=True)
        try:
            value = int(raw)
        except ValueError:
            print(level_text("ERROR", 'Must be an integer.'))
            continue
        if min_value <= value <= max_value:
            return value
        print(level_text("ERROR", tf('Value out of range ({}-{}).', min_value, max_value)))


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
        print(level_text("ERROR", 'Value is required.'))


def ask_bool(label: str, default: bool = True) -> bool:
    yes_letter = "S" if current_language() == "es" else "Y"
    marker = f"{yes_letter}/n" if default else f"{yes_letter.lower()}/N"
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
        print(level_text("ERROR", "Answer 'yes'/'y' or 'no'/'n' (Enter = default)."))


def choose(label: str, options: list[str], default_index: int | None = None) -> str:
    """Render a numbered menu with a consistent ``0)`` cancel entry.

    If ``options`` already contains a cancel-like entry (``Cancelar``/``Volver``/
    ``Salir``), that is the ``0`` option and selecting it returns that string.
    Otherwise a synthetic ``0) Cancelar`` is shown and selecting it (or pressing
    Enter with no default) returns ``""`` — the sentinel every caller treats as
    "cancelled".
    """
    print(title(label))
    zero_candidates = ['Cancel', 'Back', 'Exit']
    zero_option = next((item for item in zero_candidates if item in options), None)
    zero_label = zero_option if zero_option is not None else 'Cancel'

    indexed_options = [option for option in options if option != zero_option]

    # Options are shown translated but the ORIGINAL string is returned, so caller
    # comparisons against the source (Spanish) options keep working.
    print(f"  {style('0)', 'blue', 'bold')} {t(zero_label)}")

    for index, option in enumerate(indexed_options, start=1):
        default_tag = (
            " (default)"
            if default_index is not None and options[default_index] == option
            else ""
        )
        marker = style(f"{index})", "blue", "bold")
        print(f"  {marker} {t(option)}{style(default_tag, 'dim')}")

    while True:
        raw = input(f"{prompt_label('Select an option')}: ").strip()
        if raw == "0":
            return zero_option if zero_option is not None else ""

        if not raw:
            if default_index is not None:
                return options[default_index]
            print(level_text("INFO", 'No selection (0 to cancel).'))
            return ""
        try:
            selected = int(raw)
        except ValueError:
            print(level_text("ERROR", 'Enter the option number.'))
            continue
        if 1 <= selected <= len(indexed_options):
            return indexed_options[selected - 1]
        print(level_text("ERROR", 'Option out of range.'))


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
            print(f"\n{title('Select required file')}: {requested_label}")
        print(f"{title('Current directory')}: {current}")
        if _last_selected_dir and _last_selected_dir.is_dir():
            print(level_text("INFO", tf('Last folder used: {}', _last_selected_dir)))
        entries = sorted(
            current.iterdir(), key=lambda item: (item.is_file(), item.name.lower())
        )
        print(t('  0) Choose this directory'))
        print(t('  ..) Up one level'))
        print(t('  q) Cancel'))
        for index, entry in enumerate(entries, start=1):
            marker = "/" if entry.is_dir() else ""
            print(f"  {index}) {entry.name}{marker}")

        raw = input(f"{prompt_label("Choose a number, '..', 'q' or a manual path")}: ").strip()
        if raw.lower() in {"q", "cancelar"}:
            return ""
        if raw == "0":
            manual = input(
                f"{prompt_label('File name in this directory (or Enter for a manual path)')}: "
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
            manual_path = input(f"{prompt_label('Full file path')}: ").strip()
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

        print(level_text("ERROR", 'Invalid input.'))


def clear_screen() -> None:
    command = "cls" if os.name == "nt" else "clear"
    os.system(command)


def confirm_with_phrase(label: str, phrase: str) -> bool:
    print(title(label))
    value = input(
        f"{prompt_label('Type exactly')} {style(phrase, 'magenta', 'bold')} {prompt_label('to confirm')}: "
    ).strip()
    return value == phrase
