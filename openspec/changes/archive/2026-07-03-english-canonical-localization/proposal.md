# Make English the canonical source language and complete UI coverage

## Why

The first localization pass kept Spanish as the in-code source and translated to English on
demand. Two problems remained:

1. **Coverage was incomplete.** Only menus, prompts, titles, and table *headers* went through the
   translation chokepoints. Command (plan) descriptions, table *row* cells, status labels/defaults,
   interpolated (f-string) messages, and many one-off prints stayed in Spanish, so selecting English
   still showed Spanish text throughout.
2. **The source language was backwards.** Spanish string literals as catalog keys made the code the
   less-standard artifact. English is the expected default and the natural lingua-franca for the code.

## What Changes

- **English becomes the canonical source**: every user-facing string literal in the code is English;
  the translation catalog is inverted to English → Spanish and consulted only when Spanish is selected.
- **English becomes the default language** when neither `OIM_LANG` nor an interactive choice applies.
- **Coverage is completed** so nothing renders in Spanish under English: command/plan descriptions,
  table row cells (via the render chokepoint), interpolated messages (`tf`), status labels, and prints.
- **Fallback direction flips** to English (an uncatalogued string degrades to its English source).
- **Localized yes/no shortcut**: the boolean prompt shows `S/n` in Spanish and `Y/n` in English.

## Impact

- Affected spec: `ui-localization` (MODIFIED).
- Affected code: `instance_manager/i18n.py` (inverted catalog + English-identity `t`/`tf`), the display
  chokepoints (`ui.render_table` now translates string cells; `system.preview/apply` translate the
  description), and every module's user-facing literals (now English).
- No behavior change for non-UI logic: menu selections still act on the returned (now English) option,
  and comparisons flip alongside the option literals.
