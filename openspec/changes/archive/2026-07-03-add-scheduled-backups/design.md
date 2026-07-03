# Design

## Why systemd timer (not cron)

systemd timers integrate with the units this tool already manages, support `Persistent=true` (catch-up after
downtime), and give clean `systemctl status` / `list-timers` introspection for the "Ver estado" view.

## Artifacts (per instance `odoo-backup-<instance>`)

- **Script** `/usr/local/sbin/odoo-backup-<instance>.sh` (mode 750, `set -euo pipefail`): atomic DB dump
  (`sudo -u postgres pg_dump -Fc <db>` to a `.partial`, `mv` on success), optional filestore tarball, and
  retention (`ls -1t … | tail -n +<keep+1> | xargs -r rm -f`) for each kind.
- **Service** (`Type=oneshot`, `After=postgresql.service`, `ExecStart=<script>`).
- **Timer** (`OnCalendar=<schedule>`, `Persistent=true`, `WantedBy=timers.target`).

`daemon-reload` + `enable --now <timer>` activate it. `OnCalendar` is chosen from Diario `*-*-* 02:30:00`,
Semanal `Sun *-*-* 03:00:00`, or Mensual `*-*-01 03:30:00`.

## Local peer auth (no stored password)

The script uses `sudo -u postgres pg_dump`, which authenticates via local peer auth — so **no database password
is written to disk** in a unit or script. This is why remote databases are out of scope for scheduling.

## Testing

Pure planners are unit-tested: the plan writes script/service/timer with the right paths and `OnCalendar`,
dumps the named DB, enables the timer, omits the filestore when declined, and the removal plan disables the
timer and deletes the files. The interactive configure/status and the actual timer run are operator-accepted.
