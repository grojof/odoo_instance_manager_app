## MODIFIED Requirements

### Requirement: Optional wkhtmltopdf provisioning

During provisioning the tool SHALL offer to install `wkhtmltopdf`, explaining that Odoo's PDF reports
(invoices, quotations, and similar) require it. The recommended option SHALL install the Qt-patched
0.12.6 build selected for the detected OS codename from a pinned table (asset URL + SHA-256), verified
by checksum before installation; the tool SHALL also offer the distribution package as a clearly
labelled reduced-fidelity fallback, and a skip option. When the operator skips, the tool SHALL warn
that PDF report generation will fail until wkhtmltopdf is installed.

#### Scenario: Operator is offered wkhtmltopdf with the reports rationale

- **WHEN** the operator provisions an Odoo instance
- **THEN** the tool offers to install wkhtmltopdf and states that PDF reports require it

#### Scenario: Recommended install uses the checksum-verified patched build for the codename

- **WHEN** the operator accepts the recommended wkhtmltopdf option
- **THEN** the plan selects the patched 0.12.6 asset mapped to the detected OS codename (or the closest
  ABI-compatible build when the codename has no native asset), downloads it into a private temporary
  directory, and installs it only if its SHA-256 matches the pinned checksum, in the same step

#### Scenario: Distribution package is offered as a reduced-fidelity fallback

- **WHEN** the operator chooses the distribution package instead
- **THEN** the plan installs the distro `wkhtmltopdf`, labelled as un-patched/reduced-fidelity

#### Scenario: Unmapped codename avoids guessing a download

- **WHEN** the detected codename has no mapped patched asset and no ABI-compatible fallback
- **THEN** the tool does not fabricate a download URL and instead recommends the distribution package
  or skipping

#### Scenario: Skipping warns that PDF reports will fail

- **WHEN** the operator skips wkhtmltopdf installation
- **THEN** the tool warns that PDF report generation will fail until wkhtmltopdf is installed
