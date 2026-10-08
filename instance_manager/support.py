"""Per-version facts for installing Odoo: which Python, which setuptools, which
PostgreSQL floor, and which core repository.

Pure data, no I/O. Every bound names the evidence behind it, because only Odoo 19
states a Python maximum outright: the other maxima are derived from the newest
interpreter bucket each branch's own ``requirements.txt`` declares, and must not be
presented as something Odoo requires. The facts are the ones the sibling project
odoo_dwg keeps in its support matrix (``docs/reference/support-matrix.md``,
re-derived by its ``tools/verify_support_matrix.py``), where every Odoo version
12-19 was built and started on Ubuntu 24.04.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

OFFICIAL = "official"  # stated outright by Odoo
DERIVED = "derived"  # deduced from an official artifact (requirements.txt)
UNTESTED = "untested"  # no source states it

# The cores an instance can run: official Odoo, or OCA's OCB (the same code plus
# backported fixes, with the same branch names).
CORE_URLS: dict[str, str] = {
    "odoo": "https://github.com/odoo/odoo.git",
    "ocb": "https://github.com/OCA/OCB.git",
}
CORE_LABELS: dict[str, str] = {"odoo": "Odoo (official)", "ocb": "OCB (OCA backports)"}

# uv provides an interpreter when the host's python3 is outside a version's range.
# Pinned with the SHA-256 GitHub publishes next to each asset (release 0.12.15,
# 2026-09-15): https://github.com/astral-sh/uv/releases/tag/0.12.15
UV_VERSION = "0.12.15"
UV_ASSETS: dict[str, tuple[str, str]] = {
    "x86_64": (
        "uv-x86_64-unknown-linux-gnu.tar.gz",
        "f97935763c04be3e692460a7aaeaaab8fc3b78fcf8b389da820b38ae7423a638",
    ),
    "aarch64": (
        "uv-aarch64-unknown-linux-gnu.tar.gz",
        "0e9a3499b0587d449c9ff684c0160da607826e4af1cee220bc87f378702d3e08",
    ),
}
# Where uv keeps the interpreters it installs: shared, root-owned, readable by every
# instance user. Outside /opt/odoo so it is never listed as an instance.
UV_PYTHON_DIR = "/opt/odoo-python"

HOST = "host"
UV = "uv"


def _docs(version: str) -> str:
    major = int(version.split(".")[0])
    if major <= 13:
        page = "setup/install.html"
    elif major == 14:
        page = "administration/install/source.html"
    else:
        page = "administration/on_premise/source.html"
    return f"https://www.odoo.com/documentation/{version}/{page}"


def _bucket(version: str, distro: str) -> str:
    return f"odoo/odoo@{version} requirements.txt — newest interpreter bucket targets {distro}"


@dataclass(frozen=True)
class VersionSupport:
    major: int
    python_min: str
    python_min_source: str
    python_max: str | None
    python_max_tier: str
    python_max_source: str
    # The interpreter uv installs when the host's is not usable: one odoo_dwg has
    # built and started this version on.
    recommended_python: str
    postgres_min: int | None
    postgres_min_source: str

    @property
    def branch(self) -> str:
        return f"{self.major}.0"


ODOO_SUPPORT: dict[int, VersionSupport] = {
    12: VersionSupport(12, "3.5", _docs("12.0"), None, UNTESTED,
                       "no requirements bucket names a distribution", "3.8",
                       None, 'the docs say only "the latest version of PostgreSQL"'),
    13: VersionSupport(13, "3.6", "odoo/odoo@13.0 setup.py python_requires", None, UNTESTED,
                       "no requirements bucket names a distribution", "3.8",
                       None, "the 13.0 install page states no floor"),
    14: VersionSupport(14, "3.7", _docs("14.0"), "3.10", DERIVED, _bucket("14.0", "Ubuntu 22.04 Jammy"),
                       "3.8", 12, _docs("14.0")),
    15: VersionSupport(15, "3.7", _docs("15.0"), "3.12", DERIVED, _bucket("15.0", "Ubuntu 24.04 Noble"),
                       "3.12", 12, _docs("15.0")),
    16: VersionSupport(16, "3.7", _docs("16.0"), "3.13", DERIVED, _bucket("16.0", "Debian 13 Trixie"),
                       "3.12", 12, _docs("16.0")),
    17: VersionSupport(17, "3.10", _docs("17.0"), "3.14", DERIVED,
                       _bucket("17.0", "Ubuntu 26.04 Resolute"), "3.12", 12, _docs("17.0")),
    18: VersionSupport(18, "3.10", _docs("18.0"), "3.14", DERIVED,
                       _bucket("18.0", "Ubuntu 26.04 Resolute"), "3.12", 12, _docs("18.0")),
    19: VersionSupport(19, "3.10", "odoo/odoo@19.0 odoo/release.py MIN_PY_VERSION", "3.14", OFFICIAL,
                       "odoo/odoo@19.0 odoo/release.py MAX_PY_VERSION", "3.12", 13, _docs("19.0")),
}

# Odoo <= 16 imports pkg_resources at startup (odoo/modules/module.py), which
# setuptools removed in 81; Odoo <= 13 requires vatnumber==1.2, whose setup.py
# still uses use_2to3, removed in setuptools 58.
PKG_RESOURCES_LAST_MAJOR = 16
USE_2TO3_LAST_MAJOR = 13

# Odoo 16-19 pin gevent==21.8.0 / greenlet==1.1.2 for python_version == '3.10'
# (their Jammy row). That gevent predates CPython 3.10 — no cp310 wheel — and its
# sdist no longer compiles under a current Cython, so a 3.10 host cannot install
# them with pip (odoo_dwg hit this and repairs it with uv overrides for its
# migration steps). An instance avoids the row instead: uv's 3.12.
GEVENT_PY310_FIRST_MAJOR = 16

# Requirements an instance installs in place of one its branch pins:
# ``{major: (dropped project, replacement)}``. Odoo 12 pins pyldap==2.4.28, a
# deprecated fork ("merged back into python-ldap") that no longer builds; 13.0
# pins python-ldap==3.1.0 for the same `ldap` module.
REQUIREMENT_SUBSTITUTES: dict[int, tuple[str, str]] = {12: ("pyldap", "python-ldap==3.1.0")}

# Odoo <= 18 loads demo data into a new database unless told not to; 19 loads none
# unless asked (`--with-demo`).
DEMO_BY_DEFAULT_LAST_MAJOR = 18


def major_of(version: str) -> int | None:
    match = re.match(r"^\s*(\d{1,2})", version or "")
    return int(match.group(1)) if match else None


def version_support(version: str) -> VersionSupport | None:
    major = major_of(version)
    return ODOO_SUPPORT.get(major) if major is not None else None


def supported_majors_text() -> str:
    return ", ".join(str(major) for major in sorted(ODOO_SUPPORT))


def python_tuple(python: str) -> tuple[int, ...]:
    return tuple(int(part) for part in python.split(".") if part.isdigit())


def python_in_range(support: VersionSupport, python: str) -> bool:
    candidate = python_tuple(python)[:2]
    if candidate < python_tuple(support.python_min)[:2]:
        return False
    return not (support.python_max and candidate > python_tuple(support.python_max)[:2])


def host_python_usable(support: VersionSupport, host_python: str | None) -> bool:
    """Whether the host's python3 can build this version's requirements.

    Inside the range, except: with no stated maximum (12, 13) only up to the
    recommendation — on 3.12 their pinned gevent does not even build — and never
    3.10 for 16-19 (see ``GEVENT_PY310_FIRST_MAJOR``)."""
    if not host_python or not python_in_range(support, host_python):
        return False
    if support.python_max is None and python_tuple(host_python) > python_tuple(support.recommended_python):
        return False
    return not (support.major >= GEVENT_PY310_FIRST_MAJOR and python_tuple(host_python)[:2] == (3, 10))


def choose_python(support: VersionSupport, host_python: str | None) -> tuple[str, str]:
    """``(python, source)``: the host's when usable, else uv's recommendation."""
    if host_python_usable(support, host_python):
        return host_python or "", HOST
    return support.recommended_python, UV


def setuptools_requirement(major: int) -> str:
    if major <= USE_2TO3_LAST_MAJOR:
        return "setuptools<58"
    if major <= PKG_RESOURCES_LAST_MAJOR:
        return "setuptools<81"
    return "setuptools"


def python_range_text(support: VersionSupport) -> str:
    upper = support.python_max or "no maximum stated"
    if support.python_max and support.python_max_tier != OFFICIAL:
        upper += f" ({support.python_max_tier})"
    return f"{support.python_min} – {upper}"
