# Reportes Instagram

Pequeña web app privada para ver métricas de Instagram Business.

**Stack:** Python + Flask (gunicorn + nginx en deploy), SQLite, HTML
server-side, Chart.js. OAuth vía Facebook Login y datos vía Instagram Graph
API (versión configurable, ver `GRAPH_API_VERSION`).

> Estado: scaffolding (SPEC 01) + login OAuth con Facebook (SPEC 02). La
> bajada de datos / métricas llega en specs posteriores.

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
flask init-db          # crea/actualiza tablas (account_snapshots, post_metrics)
flask fetch-insights   # baja y persiste insights de cada usuaria guardada
```

- `account_snapshots`: un snapshot por día por usuaria (alimenta gráficos de
  evolución). Correrlo dos veces el mismo día actualiza, no duplica.
- `post_metrics`: métricas por post (upsert por `media_id`).

La bajada es **defensiva**: si una métrica falla o Meta la rechaza, se saltea y
sigue con las demás. Las métricas ausentes quedan en `NULL` (nunca 0). El token
se descifra sólo para la llamada y nunca se loguea. La automatización por cron
llega en una fase posterior.

## Requisitos

- Python 3.9+

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
