## ADDED Requirements

### Requirement: Grouped management menu

The instance-management menu SHALL present its actions in grouped submenus — **Status & health**,
**Configuration**, and **Backups & duplication** — plus a top-level **Delete instance**, so the top menu stays
short. Selecting a group SHALL open a submenu of its actions, each of which behaves exactly as before.

#### Scenario: Actions are grouped into submenus

- **WHEN** the operator opens the management menu for an instance
- **THEN** the top menu shows the group entries (Status & health, Configuration, Backups & duplication) plus
  Delete instance, and selecting a group opens a submenu listing that group's actions with a Back entry

#### Scenario: Delete instance stays top-level

- **WHEN** the operator selects Delete instance from the top menu
- **THEN** the destructive delete flow (with its phrase confirmation) runs directly, not nested in a submenu
