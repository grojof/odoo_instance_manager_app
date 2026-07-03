## ADDED Requirements

### Requirement: Secret input is not echoed

Password prompts that have no visible default SHALL read the secret without echoing it to the screen.

#### Scenario: DB and admin passwords are read without echo

- **WHEN** the operator is prompted for a DB password (backup/restore/duplicate/delete, or DB listing) or the
  purge admin password
- **THEN** the input is read via a no-echo prompt so the password is not displayed as it is typed
