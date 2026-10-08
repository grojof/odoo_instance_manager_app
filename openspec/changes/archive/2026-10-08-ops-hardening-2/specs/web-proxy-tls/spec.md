## MODIFIED Requirements

### Requirement: TLS certificate modes

For HTTPS, the tool SHALL offer four certificate strategies: do not touch
certificates, self-signed (detect or generate), Let's Encrypt (externally
managed), and copy operator-supplied CRT/KEY with an optional intermediate.

#### Scenario: Self-signed is reused or generated

- **WHEN** the self-signed strategy is chosen
- **THEN** the plan reuses an existing key/fullchain if present, otherwise generates a 2048-bit self-signed certificate for the domain, and sets `root:www-data` ownership with `640`/`644` permissions

#### Scenario: Let's Encrypt and untouched use the files that are there

- **WHEN** the Let's Encrypt strategy is chosen
- **THEN** the plan adds no certificate commands and the vhost names `/etc/letsencrypt/live/<domain>/fullchain.pem`
  and `privkey.pem`; **WHEN** do-not-touch is chosen, it names the files the current vhost names (certbot's
  included), or else the tool's own

#### Scenario: No certificate, no HTTPS vhost

- **WHEN** the files a strategy names do not exist, or a certificate file pick is cancelled
- **THEN** the tool says which file is missing and writes no HTTPS vhost (`nginx -t` would refuse it)
