"""Lightweight, modular UI translation.

Spanish is the source language (the string in the code is the key). Translation
happens at a few display/input chokepoints (see ``ui``/``prompts``), so call
sites are untouched. Any string missing from the catalog falls back to Spanish,
so partial translation degrades gracefully. Interpolated (f-string) messages are
not translated — only static UI strings (menus, labels, titles, headers).
"""

from __future__ import annotations

_LANG = "es"


def set_language(lang: str) -> None:
    global _LANG
    _LANG = "en" if str(lang).lower().startswith("en") else "es"


def current_language() -> str:
    return _LANG


def t(text: str) -> str:
    """Translate a static UI string to the current language (Spanish → English)."""
    if _LANG == "es":
        return text
    return _EN.get(text, text)


# Spanish → English catalog for the static UI (menus, prompts, titles, headers).
_EN: dict[str, str] = {
    # --- startup banner ---
    "- Instalación interactiva por instancia": "- Interactive per-instance installation",
    "- Soporta instancia Odoo + usuario de PostgreSQL, PosgreSQL o ambos": "- Supports an Odoo instance + PostgreSQL user, PostgreSQL, or both",
    "- Muestra el listado de comandos a ejecutar para cada acción": "- Shows the list of commands to run for each action",
    # --- main menu (odoo_instance_manager.py) ---
    "\n¿Qué quieres hacer?": "\nWhat do you want to do?",
    "Servicios instancias": "Instance services",
    "Gestionar instancias": "Manage instances",
    "Seguridad Fail2ban": "Fail2ban security",
    "Firewall (UFW)": "Firewall (UFW)",
    "Menú de instalación": "Installation menu",
    "Eliminar instancias (Incluye configs, servicios, logs, etc.)": "Remove instances (configs, services, logs, …)",
    "Informe para servidor externo": "External server report",
    "Salir": "Exit",
    "\nSaliendo.": "\nExiting.",
    "\nOperación interrumpida. Volviendo al menú.": "\nOperation interrupted. Returning to the menu.",
    "\nEntrada cerrada. Saliendo.": "\nInput closed. Exiting.",
    # --- installation menu ---
    "\nMenú de instalación": "\nInstallation menu",
    "Instalar instancia Odoo": "Install Odoo instance",
    "Instalar PostgreSQL (sin Odoo)": "Install PostgreSQL (without Odoo)",
    "Instalar instancia Odoo + PostgreSQL": "Install Odoo instance + PostgreSQL",
    "Volver": "Back",
    "Cancelar": "Cancel",
    "Confirmar acción": "Confirm action",
    "Confirmar plan y ejecutar": "Confirm plan and run",
    "Modo Nginx para la instancia": "Nginx mode for the instance",
    "No tocar Nginx": "Leave Nginx untouched",
    "Configurar HTTP": "Configure HTTP",
    "Configurar HTTPS": "Configure HTTPS",
    # --- manage-instance menu ---
    "Consultar ubicaciones/config actual": "Show locations / current config",
    "Comprobar salud (health check)": "Health check",
    "Actualizar configuración existente": "Update existing configuration",
    "Reparar logs Nginx de instancia": "Repair instance Nginx logs",
    "Rotación de logs": "Log rotation",
    "Uso de disco y limpieza": "Disk usage and cleanup",
    "Instalar paquetes Python en venv": "Install Python packages in the venv",
    "Inventario de addons": "Addon inventory",
    "Realizar backup": "Create backup",
    "Backups programados": "Scheduled backups",
    "Restaurar backup": "Restore backup",
    "Duplicar instancia": "Duplicate instance",
    "Eliminar instancia": "Delete instance",
    # --- services menu ---
    "Acciones de servicios": "Service actions",
    "Seleccionar servicio": "Select a service",
    "Refrescar": "Refresh",
    "Iniciar": "Start",
    "Detener": "Stop",
    "Reiniciar": "Restart",
    "Habilitar autoarranque": "Enable autostart",
    "Deshabilitar autoarranque": "Disable autostart",
    "Escribir nombre": "Type a name",
    # --- fail2ban menu ---
    "Gestión de Fail2ban": "Fail2ban management",
    "Instalar/config base segura": "Install / configure secure baseline",
    "Activar protección Odoo por instancia": "Enable per-instance Odoo protection",
    "Verificar IP real en log Odoo": "Check real IP in the Odoo log",
    "Ver estado y jails": "Show status and jails",
    "Ver detalle de jail": "Show jail detail",
    "Desbanear IP de jail": "Unban an IP from a jail",
    "Probar regex Odoo": "Test the Odoo regex",
    # --- firewall menu ---
    "Permitir puerto": "Allow a port",
    "Eliminar regla (por número)": "Delete a rule (by number)",
    "Habilitar UFW": "Enable UFW",
    "Deshabilitar UFW": "Disable UFW",
    "Protocolo": "Protocol",
    # --- log rotation / disk / scheduled / addons submenus ---
    "Consultar rotación actual": "Show current rotation",
    "Configurar rotación (system logrotate)": "Configure rotation (system logrotate)",
    "Ver uso de disco": "Show disk usage",
    "Limpiar backups antiguos (retención)": "Prune old backups (retention)",
    "Configurar backup programado": "Configure scheduled backup",
    "Ver estado": "Show status",
    "Eliminar programación": "Remove schedule",
    "Frecuencia": "Frequency",
    "Frecuencia de rotación": "Rotation frequency",
    # --- backup / restore / duplicate modes ---
    "Tipo de backup": "Backup type",
    "Solo DB": "Database only",
    "Solo Filestore": "Filestore only",
    "DB + Filestore": "Database + Filestore",
    "Tipo de restauración": "Restore type",
    "Modo de operación (equivalente Odoo)": "Operation mode (Odoo equivalent)",
    "Modo de duplicación": "Duplication mode",
    "Copiada (nuevo UUID en destino)": "Copied (new UUID on target)",
    "Movida (mantener UUID)": "Moved (keep UUID)",
    # --- certificates ---
    "Gestión de certificados para HTTPS": "HTTPS certificate management",
    "No tocar certificados": "Leave certificates untouched",
    "Autofirmado (detectar o generar automáticamente)": "Self-signed (detect or generate automatically)",
    "Let's Encrypt (gestionado externamente)": "Let's Encrypt (managed externally)",
    "Copiar certificados propios (CRT/KEY[/Intermediate])": "Copy your own certificates (CRT/KEY[/Intermediate])",
    # --- common yes/no & value prompts ---
    "Nombre de instancia": "Instance name",
    "DB server": "DB server",
    "DB port": "DB port",
    "DB user": "DB user",
    "DB password": "DB password",
    "Directorio destino de backup": "Backup destination directory",
    "Puerto a permitir": "Port to allow",
    "Puerto SSH a permitir": "SSH port to allow",
    "¿Permitir HTTP (80)?": "Allow HTTP (80)?",
    "¿Permitir HTTPS (443)?": "Allow HTTPS (443)?",
    "¿Comprimir logs rotados?": "Compress rotated logs?",
    "¿Incluir también el filestore?": "Include the filestore as well?",
    "Selecciona opción": "Select an option",
    # --- common table headers ---
    "Estado": "State",
    "Chequeo": "Check",
    "Detalle": "Detail",
    "Elemento": "Item",
    "Valor": "Value",
    "Ruta": "Path",
    "Ruta/Valor": "Path/Value",
    "Tamaño": "Size",
    "Campo": "Field",
    "Clave": "Key",
    "Módulo": "Module",
    "Versión (manifest)": "Version (manifest)",
    "Versión instalada": "Installed version",
    "Servicio": "Service",
    "Arranque": "Startup",
    "#": "#",
    "Acción": "Action",
    "Comando": "Command",
    # --- frequent titles ---
    "Plan de ejecución": "Execution plan",
}
