# Relevamiento del VPS (deploy Fase 2)

> Nota: este repo es **público**. Este documento contiene sólo los hechos
> necesarios para el deploy; se omiten a propósito la IP del servidor, los demás
> dominios alojados y el layout interno del server.

Hechos confirmados (read-only) para diseñar el deploy:

| Ítem | Estado |
| --- | --- |
| **Python** | 3.12.3 como `python3` del sistema → cumple 3.10+ (gunicorn 26 OK). No hay que instalar. |
| **OS / arch** | Ubuntu 24.04 LTS, x86_64. |
| **Recursos** | RAM suficiente para un Flask chico. Disco ~76% usado → **monitorear**, no bloqueante (SQLite pesa poco). |
| **nginx** | 1.24, multi-sitio. Patrón a seguir: subdominio → `proxy_pass` a un puerto local + SSL de certbot + redirect http→https. |
| **Puerto gunicorn** | `127.0.0.1:8000` (libre, confirmado). |
| **HTTPS** | certbot + Let's Encrypt operativos (`certbot --nginx -d <subdominio>`), renovación automática. |
| **Procesos** | systemd 255 disponible → gunicorn como servicio. fail2ban activo. No hay app-server propio corriendo. |
| **DNS** | A record `reportes.lahuelladelcaminante.de` → VPS **ya creado** (confirmado). |
| **cron** | `crontab` disponible y `cron.service` activo/enabled. |

Conclusión: no hay bloqueantes. Seguir el patrón de subdominio existente para
nginx + certbot, gunicorn como servicio systemd en `127.0.0.1:8000`, y enchufar
el cron de la Fase 3.
