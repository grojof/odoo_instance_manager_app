## ADDED Requirements

### Requirement: Production posture reporting

The report SHALL include, per discovered instance, a production-posture summary derived read-only from
each instance config and the host: database-manager exposure (`list_db`), the presence of a guessable
default master or DB password, worker sizing versus detected CPU, `db_sslmode` for remote database
hosts, and `dbfilter` presence; and it SHALL report the host `wkhtmltopdf` version once. The summary
SHALL NOT modify anything.

#### Scenario: Posture is reported per instance

- **WHEN** the report is generated
- **THEN** each discovered instance shows its `list_db`, credential-default, worker-sizing,
  remote-`db_sslmode`, and `dbfilter` posture with an OK/WARN/INFO classification

#### Scenario: Host wkhtmltopdf version is reported

- **WHEN** the report is generated
- **THEN** the host `wkhtmltopdf` version is reported (or a not-detected marker), and a missing or
  un-patched build is flagged as WARN

#### Scenario: Posture reporting performs no mutation

- **WHEN** the posture summary is produced
- **THEN** only read-only inspection of configs and host state occurs and no install, configuration,
  or deletion command is produced or applied
