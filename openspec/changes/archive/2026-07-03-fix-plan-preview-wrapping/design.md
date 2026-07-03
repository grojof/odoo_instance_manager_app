# Design

## Why a list, not a table, for the plan preview

A command can be long and multi-line (the `odoo.conf` / systemd / nginx writers use `cat > file <<'EOF' … EOF`
heredocs). Cramming that into a fixed table column is inherently awkward: even with wrapping, a 20-line cell in
one column reads badly. A list — description, then the command indented below — matches how the operator reads
a plan and lets commands use the full width.

```
[02] Escribir /etc/odoo/inst/inst.conf
     cat > '/etc/odoo/inst/inst.conf' <<'EOF'
     [options]
     addons_path = /opt/odoo/inst/odoo/addons,/opt/odoo/inst/
     addons-oca,/opt/odoo/inst/addons-custom
     EOF
```

`preview_commands` computes `body_width = terminal_columns - len(indent)` and wraps each command line via
`wrap_plain_block`, styling each wrapped line dim.

## ANSI-robust `_wrap_cell` (general table fix)

The root cause of the residual bug was that `_wrap_cell` skipped any line containing ANSI, so a fully-styled
long cell never wrapped. It now wraps the **visible** text (`strip_ansi`) and re-applies the line's leading SGR
run (`_leading_sgr`) and trailing reset to each wrapped chunk. This keeps escape sequences intact, wraps long
styled content, and leaves short styled tags (≤ cap) untouched. `wrap_plain_block` is the shared line-wrapping
primitive.

## Testing

`tests/test_ui.py` adds: `wrap_plain_block` wraps each line within width (and returns `[""]` for empty), and a
long **dim-styled** table cell both wraps within `max_width` and keeps its `\033[2m…` escapes. The interactive
`preview_commands` output is verified by operator acceptance (and a manual `COLUMNS=60` render during
development).
