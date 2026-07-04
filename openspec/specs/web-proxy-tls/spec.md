# web-proxy-tls Specification

## Purpose

Configure the Nginx reverse proxy that fronts an Odoo instance, in HTTP or HTTPS
mode, and manage the TLS material for HTTPS: self-signed generation, copying
operator-supplied certificates (with validation), or deferring to externally
managed Let's Encrypt.
## Requirements
### Requirement: Nginx proxy modes

The tool SHALL support three Nginx modes per instance: leave Nginx untouched,
configure HTTP, or configure HTTPS. Selecting HTTP or HTTPS SHALL make the two
modes mutually exclusive by enabling one vhost and removing the other.

#### Scenario: HTTP mode enables the HTTP vhost only

- **WHEN** the operator selects HTTP mode
- **THEN** the plan writes and enables the `<instance>-http.conf` vhost, removes any enabled `<instance>-https.conf`, validates with `nginx -t`, and reloads Nginx

#### Scenario: HTTPS mode enables the HTTPS vhost only

- **WHEN** the operator selects HTTPS mode
- **THEN** the plan writes and enables the `<instance>-https.conf` vhost (HTTP→HTTPS redirect plus TLS server), removes any enabled `<instance>-http.conf`, validates with `nginx -t`, and reloads Nginx

#### Scenario: Untouched mode changes nothing

- **WHEN** the operator selects to not touch Nginx
- **THEN** no Nginx command is added to the plan

### Requirement: Proxy vhost contents

Generated vhosts SHALL proxy to the instance's internal HTTP and gevent ports, include a dedicated
live-chat/bus upstream with connection-upgrade handling, and set forwarded headers for proxy mode. The
vhost SHALL adapt to the detected environment: the HTTP/2 form matches the detected nginx version
(`listen … ssl http2` on nginx < 1.25.1, `listen … ssl` + `http2 on;` on ≥ 1.25.1), and the live-chat
location matches the Odoo major (`/websocket` on Odoo ≥ 16, `/longpolling/poll` on Odoo ≤ 15).

#### Scenario: Websocket and forwarded headers are configured

- **WHEN** a vhost is generated
- **THEN** it defines `odoo_<instance>` and `odoochat_<instance>` upstreams, a live-chat location with
  `Upgrade`/`Connection` headers, and `X-Forwarded-*`/`X-Real-IP` headers on all locations

#### Scenario: HTTP/2 directive matches the detected nginx version

- **WHEN** an HTTPS vhost is generated on a host whose nginx version is detected
- **THEN** nginx ≥ 1.25.1 uses `listen … ssl;` with a separate `http2 on;`, and nginx < 1.25.1 uses the
  `listen … ssl http2;` form, so `nginx -t` passes on either version

#### Scenario: Live-chat location matches the Odoo major

- **WHEN** a vhost is generated for an instance of a known Odoo major
- **THEN** Odoo ≥ 16 gets a `/websocket` location and Odoo ≤ 15 gets a `/longpolling/poll` location,
  both proxying to the instance gevent/longpolling upstream

### Requirement: TLS certificate modes

For HTTPS, the tool SHALL offer four certificate strategies: do not touch
certificates, self-signed (detect or generate), Let's Encrypt (externally
managed), and copy operator-supplied CRT/KEY with an optional intermediate.

#### Scenario: Self-signed is reused or generated

- **WHEN** the self-signed strategy is chosen
- **THEN** the plan reuses an existing key/fullchain if present, otherwise generates a 2048-bit self-signed certificate for the domain, and sets `root:www-data` ownership with `640`/`644` permissions

#### Scenario: Let's Encrypt and untouched defer certificate work

- **WHEN** the Let's Encrypt or do-not-touch strategy is chosen
- **THEN** the plan adds no certificate commands, leaving certificate provisioning to the external tooling

### Requirement: Custom certificate validation

When copying operator-supplied certificates, the plan SHALL install them into a
dedicated per-instance SSL directory, build a fullchain, and validate the key,
the certificate, and that the private key matches the certificate before use.

#### Scenario: Fullchain is built from cert and intermediate

- **WHEN** an intermediate certificate is supplied
- **THEN** the plan concatenates the leaf certificate and the intermediate into the fullchain file; when no intermediate is supplied it uses the leaf as the fullchain

#### Scenario: Key/certificate mismatch aborts the plan

- **WHEN** the supplied private key's public key does not match the certificate's public key
- **THEN** the corresponding validation command fails and execution stops before Nginx is reconfigured

