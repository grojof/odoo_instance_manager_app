## ADDED Requirements

### Requirement: Replica runtime follows the source and the version

A replica created by instance duplication SHALL clone the same core as the source (OCB when the source's
checkout comes from OCA's OCB, else official Odoo), SHALL be built with the interpreter the support matrix picks
for its version on this host, and SHALL get its own data dir `/var/lib/odoo/<instance>`.

#### Scenario: An OCB source gives an OCB replica

- **WHEN** the source instance's checkout has OCA's OCB as origin
- **THEN** the replica's base setup clones OCB at the same branch
