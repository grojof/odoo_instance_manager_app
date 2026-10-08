## MODIFIED Requirements

### Requirement: Proxy vhost contents

Generated vhosts SHALL proxy to the instance's internal HTTP and gevent ports, include a dedicated
live-chat/bus upstream with connection-upgrade handling, set forwarded headers for proxy mode, accept uploads
up to 2048 MB and compress with gzip. The HTTPS vhost SHALL follow Odoo's deployment guide: its TLS settings
(TLS 1.2 and 1.3, its cipher list, `ssl_prefer_server_ciphers off`, `ssl_session_timeout 30m`), HSTS, and the
`session_id` cookie marked `secure` with `proxy_cookie_flags` on nginx ≥ 1.19.3 (the version installed, or the
one apt would install; when neither is known the directive is left out, as for an older nginx). The vhost SHALL adapt to the
detected environment: the HTTP/2 form matches the detected nginx version (`listen … ssl http2` on nginx <
1.25.1, `listen … ssl` + `http2 on;` on ≥ 1.25.1), and the live-chat location matches the Odoo major
(`/websocket` on Odoo ≥ 16, `/longpolling/poll` on Odoo ≤ 15).

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

#### Scenario: The HTTPS vhost follows Odoo's deployment guide

- **WHEN** an HTTPS vhost is generated for nginx ≥ 1.19.3
- **THEN** each location sends HSTS and marks the `session_id` cookie `secure`, and the server uses the guide's
  TLS settings
