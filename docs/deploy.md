# Deploy a producción (Fase 2)

Pone la app en `https://reportes.lahuelladelcaminante.de`: gunicorn como servicio
systemd detrás de nginx con HTTPS, conservando el token y la historia de la base.

Archivos de ejemplo: [`deploy/gunicorn.service.example`](../deploy/gunicorn.service.example)
y [`deploy/nginx-reportes.conf.example`](../deploy/nginx-reportes.conf.example).

> Convención: cada paso marcado **(S)** se ejecuta en el VPS; **(R)** ya está en
> el repo. Las acciones destructivas (sobrescribir configs, reiniciar servicios)
> se confirman antes.

## 0. Pre-requisitos
- DNS: A record `reportes.lahuelladelcaminante.de` → VPS (ya creado).
- En la consola de Meta, agregar a "URI de redireccionamiento de OAuth válidos":
  `https://reportes.lahuelladelcaminante.de/auth/callback` (dejar también el de
  ngrok para desarrollo). El login de producción usa esta.

## 1. Código y venv (S)
```bash
sudo mkdir -p /opt/reportes-instagram && sudo chown <usuario>:<grupo> /opt/reportes-instagram
git clone <repo> /opt/reportes-instagram   # o git pull si ya existe
cd /opt/reportes-instagram && git checkout main
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```
El servicio corre bajo un **usuario no privilegiado** (no root), con permisos
mínimos sobre la carpeta.

## 2. Base de datos (S — con cuidado)
La `instance/reportes.db` local tiene el **token cifrado** y la historia.
```bash
# desde la máquina local (canal seguro):
scp instance/reportes.db <usuario>@<vps>:/opt/reportes-instagram/instance/reportes.db
```
**CRÍTICO:** el `.env` de producción debe usar la **misma `TOKEN_ENCRYPTION_KEY`**
que el local. Si difiere, el token de la base copiada no se descifra y hay que
re-loguear. La base queda **fuera del webroot** y con permisos sólo para el
usuario del servicio.

## 3. `.env` de producción (S — lo carga el usuario, fuera del repo)
Crear `/opt/reportes-instagram/.env` (la app lo lee con python-dotenv). Variables
en `.env.example`; valores de prod:
- `REDIRECT_URI=https://reportes.lahuelladelcaminante.de/auth/callback`
- `SESSION_COOKIE_SECURE=True`, `FLASK_DEBUG=0`
- `TOKEN_ENCRYPTION_KEY=` **la misma que en local**
- `DATABASE=/opt/reportes-instagram/instance/reportes.db`
- `SECRET_KEY`, `FACEBOOK_APP_ID`, `FACEBOOK_APP_SECRET`, `GRAPH_API_VERSION=v23.0`
```bash
chmod 600 .env    # sólo el usuario del servicio puede leerlo
```

## 4. gunicorn como servicio systemd (S)
Copiar `deploy/gunicorn.service.example` → `/etc/systemd/system/reportes.service`,
reemplazar placeholders, y:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now reportes
curl -s http://127.0.0.1:8000/health    # {"status":"ok"}
```

## 5. nginx (S — solo agregar, no tocar otros sitios)
Copiar `deploy/nginx-reportes.conf.example` → `/etc/nginx/sites-available/reportes`,
symlink a `sites-enabled/`, validar y recargar:
```bash
sudo ln -s /etc/nginx/sites-available/reportes /etc/nginx/sites-enabled/
sudo nginx -t        # debe pasar
sudo systemctl reload nginx
```

## 6. HTTPS (S)
```bash
sudo certbot --nginx -d reportes.lahuelladelcaminante.de
```
certbot emite el cert y completa el SSL. Renovación automática (ya configurada).

## 7. Cron (S — enchufar la lógica de la app)
La app trae los comandos (ver README, sección *Mantenimiento*). Agregar al
crontab del **usuario del servicio** (orden: refresh → snapshot):
```cron
0 6 * * *  cd /opt/reportes-instagram && /opt/reportes-instagram/.venv/bin/flask refresh-tokens >> /var/log/reportes/refresh.log 2>&1
5 6 * * *  cd /opt/reportes-instagram && /opt/reportes-instagram/.venv/bin/flask daily-snapshot  >> /var/log/reportes/snapshot.log 2>&1
```
El `cd` asegura que python-dotenv lea el `.env` del working dir.

## Re-deploys futuros
```bash
cd /opt/reportes-instagram && git pull && .venv/bin/pip install -r requirements.txt
sudo systemctl restart reportes
```
