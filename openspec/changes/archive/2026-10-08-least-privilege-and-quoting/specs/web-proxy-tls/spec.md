## MODIFIED Requirements

### Requirement: Custom certificate validation

When copying operator-supplied certificates, the plan SHALL copy them into a staging directory beside the
per-instance SSL directory, build the fullchain there, validate the key, the certificate, that the private key
matches the certificate, and the fullchain, and only then move them into place, keeping the previous files as
`.previous`. Operator-supplied paths SHALL be passed to the shell quoted.

#### Scenario: Fullchain is built from cert and intermediate

- **WHEN** an intermediate certificate is supplied
- **THEN** the plan concatenates the leaf certificate and the intermediate into the fullchain file; when no intermediate is supplied it uses the leaf as the fullchain

#### Scenario: Key/certificate mismatch aborts the plan

- **WHEN** the supplied private key's public key does not match the certificate's public key
- **THEN** the step fails before any live file is replaced, and execution stops before Nginx is reconfigured

#### Scenario: A file name is a name

- **WHEN** a selected file's name holds shell syntax such as `$(…)` or a quote
- **THEN** it is copied as that file and nothing in its name runs
