# Reportes Instagram

Pequeña web app privada para ver métricas de Instagram Business.

**Stack:** Python + Flask (gunicorn + nginx en deploy), SQLite, HTML
server-side, Chart.js. OAuth vía Facebook Login y datos vía Instagram Graph
API (versión configurable, ver `GRAPH_API_VERSION`).

> Estado: scaffolding (SPEC 01) + login OAuth con Facebook (SPEC 02) + bajada
> de insights a SQLite (SPEC 03). Los gráficos / dashboard y la automatización
> por cron llegan en specs posteriores.

## Login (OAuth)

Rutas del blueprint `auth`:

- `GET /auth/login` — inicia el flujo OAuth (redirige a Facebook).
- `GET /auth/callback` — recibe el callback, valida `state`, canjea el token
  y lo guarda cifrado.
- `GET /auth/logout` — cierra la sesión.

Los access tokens se guardan **cifrados** en SQLite (Fernet), nunca en claro.

## Bajada de insights

Tras loguearte, podés bajar insights de la Instagram Graph API a mano:

```bash
flask init-db            # crea/actualiza tablas (account_snapshots, post_metrics, audience_demographics)
flask fetch-insights     # baja y persiste insights (snapshot de cuenta + posts)
flask fetch-demographics # demografía agregada de audiencia (género/edad/país/ciudad, ≥100 seg.)
```

`fetch-demographics` es "foto actual" (reemplaza en cada bajada). Los datos son
**agregados y anónimos** (Meta nunca da identidades) y pueden tardar ~48h. Los
gráficos de demografía aparecen en el dashboard cuando hay datos.

- `account_snapshots`: un snapshot por día por usuaria (alimenta gráficos de
  evolución). Correrlo dos veces el mismo día actualiza, no duplica.
- `post_metrics`: métricas por post (upsert por `media_id`).

La bajada es **defensiva**: si una métrica falla o Meta la rechaza, se saltea y
sigue con las demás. Las métricas ausentes quedan en `NULL` (nunca 0). El token
se descifra sólo para la llamada y nunca se loguea.

## Mantenimiento (renovación de token + snapshot diario)

Dos comandos mantienen la app viva en el tiempo:

```bash
flask refresh-tokens   # renueva el token largo si está cerca de vencer (cond.)
flask daily-snapshot   # snapshot diario liviano de cuenta (sin re-bajar posts)
```

- `refresh-tokens`: refresca el token de Facebook Login **sólo** si le quedan
  ≤15 días para vencer y tiene ≥24h de antigüedad; guarda el nuevo cifrado con
  su nuevo vencimiento. Es **condicional e idempotente** → correrlo a diario es
  seguro. Si el token ya venció, devuelve el `status` `expired_relogin` (es un
  valor de retorno de runtime que indica que hay que rehacer el login OAuth; no
  se persiste ningún flag en la DB). **Importante:** un token largo que pasa 60
  días sin refrescarse
  expira y ya no se puede renovar — por eso conviene el cron diario.
- `daily-snapshot`: graba el snapshot de cuenta del día (seguidores + reach),
  idempotente por día. Liviano: no re-baja los posts (eso es `fetch-insights`).

### Cron recomendado (configurar en el deploy — Fase 2, NO ahora)

En el VPS, una vez deployado, agregar al crontab (orden: primero renovar el
token, después tomar el snapshot). Ejemplo (diario 06:00, ajustar rutas):

```cron
# m h  dom mon dow   command
# 0 6  *   *   *     cd /ruta/app && /ruta/.venv/bin/flask refresh-tokens >> /var/log/reportes/refresh.log 2>&1
# 5 6  *   *   *     cd /ruta/app && /ruta/.venv/bin/flask daily-snapshot  >> /var/log/reportes/snapshot.log 2>&1
```

(Líneas comentadas a propósito: el cron se enchufa al deployar, no en desarrollo.)

## Requisitos

- Python 3.10+ (gunicorn 26 requiere 3.10+)

## Puesta en marcha (desarrollo)

```bash
# 1. Crear y activar el entorno virtual
python3 -m venv .venv
source .venv/bin/activate

# 2. Instalar dependencias
pip install -r requirements.txt

# 3. Configurar variables de entorno
cp .env.example .env
# Editá .env y completá al menos SECRET_KEY. Para generar una:
#   python -c "import secrets; print(secrets.token_hex(32))"

# 4. Inicializar la base de datos (crea instance/reportes.db)
flask init-db

# 5. Levantar la app en local
python wsgi.py
```

La app queda en `http://localhost:5000`. Verificá el health check:

```bash
curl http://localhost:5000/health
# {"status":"ok"}
```

## Configuración

Toda la configuración se lee de variables de entorno (ver `.env.example`).
Ninguna credencial se versiona ni se loguea.

| Variable              | Descripción                                         |
| --------------------- | --------------------------------------------------- |
| `SECRET_KEY`            | Clave de sesiones de Flask. **Obligatoria.**          |
| `TOKEN_ENCRYPTION_KEY`  | Clave Fernet para cifrar tokens. **Obligatoria.**     |
| `FACEBOOK_APP_ID`       | App ID de la app de Meta.                             |
| `FACEBOOK_APP_SECRET`   | App Secret de la app de Meta.                         |
| `REDIRECT_URI`          | Redirect OAuth. Debe coincidir con el registrado.    |
| `GRAPH_API_VERSION`     | Versión de la Graph API (ej. `v23.0`).               |
| `DATABASE`              | Ruta a la SQLite (default `instance/reportes.db`).   |
| `SESSION_COOKIE_SECURE` | Cookies sólo por HTTPS. `False` en local, `True` prod.|
| `FLASK_DEBUG`           | `1` activa el debugger local (default off).           |

Si falta `SECRET_KEY` o `TOKEN_ENCRYPTION_KEY` (o esta última es inválida), la
app **no arranca** y falla con un error explícito.

Generá `TOKEN_ENCRYPTION_KEY` con:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## Deploy (gunicorn)

```bash
gunicorn wsgi:app
```

## Tests

```bash
pip install pytest
pytest
```
