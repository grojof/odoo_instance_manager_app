"""Interactive workflows for the Odoo instance manager.

The implementation is split by capability across this package; this module
re-exports the stable public entry points used by ``odoo_instance_manager``.
"""

from __future__ import annotations

from .fail2ban import manage_fail2ban
from .install import install_db_only, install_odoo_and_db, install_odoo_only
from .manage import manage_existing_instance
from .purge import purge_instance_superuser
from .report import external_server_report
from .services import manage_instance_services

__all__ = [
    "external_server_report",
    "install_db_only",
    "install_odoo_and_db",
    "install_odoo_only",
    "manage_existing_instance",
    "manage_fail2ban",
    "manage_instance_services",
    "purge_instance_superuser",
]
