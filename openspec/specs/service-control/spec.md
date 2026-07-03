# service-control Specification

## Purpose

Manage the systemd services of installed Odoo instances: list detected instance
services with their run and boot state, and start, stop, restart, enable, or
disable a selected service through the standard plan/preview/apply flow.

## Requirements

### Requirement: Instance service discovery

The tool SHALL detect instance services by cross-referencing instances under
`/opt/odoo` with existing systemd units, and display each with its active state
and autostart state.

#### Scenario: Detected services show run and boot state

- **WHEN** the operator opens the services menu
- **THEN** each instance that has a systemd unit is listed as running or stopped and with autostart enabled or disabled

#### Scenario: No detected services still allows manual entry

- **WHEN** no instance services are detected
- **THEN** the operator may type a service name to act on

### Requirement: Service actions

The tool SHALL offer start, stop, restart, enable-autostart, and
disable-autostart actions for a selected service, each executed as a previewed
plan.

#### Scenario: Selected action runs the matching systemctl command

- **WHEN** the operator selects a service and an action
- **THEN** the plan contains exactly the corresponding `systemctl` command (start/stop/restart/enable/disable) for that service and runs through the standard confirm/apply flow

#### Scenario: Refresh re-reads current state

- **WHEN** the operator chooses to refresh
- **THEN** the service table is recomputed from current systemd state without executing any action
