# Reportes Instagram

Pequeña web app privada para ver métricas de Instagram Business.

**Stack:** Python + Flask (gunicorn + nginx en deploy), SQLite, HTML
server-side, Chart.js. OAuth vía Facebook Login y datos vía Instagram Graph
API v22.0.

> Estado: esqueleto inicial (SPEC 01). El login OAuth y la bajada de datos
> llegan en specs posteriores.

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
| `SECRET_KEY`          | Clave de sesiones de Flask. **Obligatoria.**        |
| `FACEBOOK_APP_ID`     | App ID de la app de Meta.                            |
| `FACEBOOK_APP_SECRET` | App Secret de la app de Meta.                        |
| `REDIRECT_URI`        | Redirect OAuth. Debe coincidir con el registrado.   |
| `GRAPH_API_VERSION`   | Versión de la Graph API (ej. `v22.0`).              |
| `DATABASE`            | Ruta a la SQLite (default `instance/reportes.db`).  |

Si falta `SECRET_KEY`, la app **no arranca** y falla con un error explícito.

## Deploy (gunicorn)

```bash
gunicorn wsgi:app
```

## Tests

```bash
pip install pytest
pytest
```
