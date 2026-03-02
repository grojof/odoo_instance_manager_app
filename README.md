# Odoo Instance Manager

Gestor interactivo para instancias Odoo con ejecución segura y planificación de comandos.

## Menú principal

1. Gestionar instancias
2. Seguridad Fail2ban
3. Menú de instalación
4. Salir

## Gestión de instancias

- Descubre instancias en `/opt/odoo`.
- Configura cada instancia en `/etc/odoo/<instancia>/<instancia>.conf`.
- Muestra resumen completo de rutas y estado técnico de la instancia.
- Permite consulta opcional a PostgreSQL para listar bases disponibles.
- Incluye acciones seguras:
	- Ver estado completo
	- Consultar ubicaciones y configuración
	- Actualizar configuración existente
	- Reparar logs Nginx de instancia
	- Realizar backup
	- Restaurar backup
	- Duplicar instancia
	- Eliminar instancia

## Menú de instalación

- Instalar SOLO Odoo
- Instalar SOLO DB
- Instalar Odoo + DB

## Seguridad Fail2ban

- Instala y configura base segura (`sshd`, `nginx-http-auth`, `nginx-botsearch`, `recidive`) con `banaction=ufw`.
- Permite activar protección por instancia Odoo con jail dedicado y filtro de intentos fallidos.
- Incluye verificación de IP real en logs Odoo para evitar baneos cuando solo llega IP interna/gateway.
- Incluye acciones de operación: ver estado/jails, ver detalle por jail, desbanear IP (con listado de IPs baneadas) y probar regex con `fail2ban-regex`.

## Requisitos

- Python 3
- Ejecución como root

## Ejecución

```bash
cd WSL_new_doc/odoo_instance_manager_app
sudo python3 odoo_instance_manager.py
```

## Comportamiento operativo

- El gestor exige ejecución con `sudo` desde el inicio.
- Cada acción genera plan de comandos antes de aplicar.
- Las operaciones sensibles requieren confirmación explícita por frase.
- Si una instalación falla durante la aplicación, se ejecuta una limpieza automática de residuos de la instancia (servicio, archivos de Odoo/Nginx/SSL y rol DB de la instancia cuando aplica) para permitir reintentos limpios.
