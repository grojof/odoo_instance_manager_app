# Tasks

## 1. Flip the catalog and translation direction
- [x] 1.1 Invert the authoring catalog to derive an English → Spanish runtime table
- [x] 1.2 Make `t`/`tf` the identity under English and look up the catalog under Spanish
- [x] 1.3 Default the language to English; keep `OIM_LANG` and the startup chooser

## 2. Flip in-code literals to English
- [x] 2.1 Replace every user-facing Spanish string literal with its English source
- [x] 2.2 Convert interpolated Spanish f-strings to `tf('<English template>', …)`
- [x] 2.3 Keep input-matching tokens (e.g. accepted `sí`) and the `Español` menu label unchanged

## 3. Complete the display chokepoints
- [x] 3.1 Translate table row *cells* (not only headers) in `render_table`
- [x] 3.2 Translate the command description in the apply/preview steps
- [x] 3.3 Localize the yes/no shortcut (`S/n` vs `Y/n`)

## 4. Verify
- [x] 4.1 Catalog covers every displayed string (descriptions, cells, prompts, tf templates)
- [x] 4.2 `ruff`, byte-compile, and `pytest` pass; tests updated for the flipped semantics
- [x] 4.3 Scan confirms no Spanish remains outside the intentional keeps
