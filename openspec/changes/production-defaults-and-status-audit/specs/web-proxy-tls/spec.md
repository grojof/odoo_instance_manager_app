## MODIFIED Requirements

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
