"""Interactive workflows for the Odoo instance manager.

This package is being split by capability; for now the implementation lives in
``_core`` and is progressively extracted into feature modules. The public entry
points re-exported here are the stable surface used by ``odoo_instance_manager``.
"""

from __future__ import annotations

from ._core import (
    install_db_only,
    install_odoo_and_db,
    install_odoo_only,
    manage_existing_instance,
)
from .fail2ban import manage_fail2ban
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
