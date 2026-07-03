# Tasks

- [x] 1.1 Add `plan_ufw_base_setup` / `plan_ufw_allow_port` / `plan_ufw_delete_rule` (pure).
- [x] 1.2 Add `workflows/firewall.py` (`manage_firewall`: status, baseline, allow, delete, enable/disable).
- [x] 1.3 Add a "Firewall (UFW)" entry to the main menu.
- [x] 2.1 Add the `firewall-ufw` spec.
- [x] 2.2 Add UFW planner tests.
- [x] 2.3 Add `docs/firewall.md`, linked from the README; note the Fail2ban dependency there.
- [x] 3.1 `ruff`, `pytest`, `openspec validate --specs`, `docs-check` pass locally.
- [ ] 3.2 (operator) On a VM: apply the baseline over SSH and confirm the session stays up and the rules are correct.
