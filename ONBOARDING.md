# Onboarding — Reportes La Huella

Guía para arrancar rápido (dev nuevo o sesión futura). Para detalles operativos
de cada cosa, ver el [README](README.md), [docs/deploy.md](docs/deploy.md) y el
[BACKLOG](BACKLOG.md).

## Qué es

App web **privada** (una usuaria) para ver métricas de una cuenta de Instagram
Business. Login con Facebook, baja insights de la Graph API a SQLite, los
muestra en un dashboard con Chart.js, y genera un reporte de texto descriptivo
con la API de Claude.

**Stack:** Python 3.10+ · Flask (app factory + blueprints) · SQLite ·
HTML server-side (Jinja2) · Chart.js (pineado + SRI) · gunicorn + nginx en
producción. Sin frontend framework, sin ORM.

**En producción:** https://reportes.lahuelladelcaminante.de — ver
[docs/deploy.md](docs/deploy.md) y la memoria de proyecto para el VPS.

## Los guardrails de datos (LO MÁS IMPORTANTE)

Es el alma del proyecto. Todo cálculo y todo texto los respeta; si tocás algo,
no los rompas:

- **NULL ≠ 0.** Una métrica ausente es `None`/NULL, **nunca 0**. No se grafica,
  no se promedia, no se muestra como 0 (el front dice "sin dato"). Un 0 falso
  arruina medianas y gráficos.
- **Medianas, no promedios.** Cuenta de bajo volumen → medianas (`_median`
  ignora None y no-números).
- **N ≥ 12 (`MIN_SAMPLE`)** para cualquier conclusión inferencial (mejores
  horarios, qué tipo conviene, tendencias). Por debajo: "muestra chica, no
  concluyente". También aplica el `n` por tipo/serie.
- **Descriptivo, sin causalidad.** Nada de "creció PORQUE…". Se describe, no se
  infiere ni se recomienda.
- **Agregado y anónimo.** La demografía es agregada (Meta nunca da identidades);
  país/ciudad con top-N + "Otros" (sin recorte silencioso). Al reporte de Claude
  se le mandan **solo agregados**: nunca tokens ni IDs internos.

Los cálculos viven en el **backend** (`app/routes/dashboard.py`), no en el JS.

## Estructura

```
app/
  __init__.py      app factory (create_app): valida SECRET_KEY + TOKEN_ENCRYPTION_KEY,
                   registra blueprints y comandos, aplica ProxyFix (nginx).
  config.py        toda la config sale de variables de entorno (.env en dev).
  db.py            conexión SQLite, init_db (schema + migraciones de columnas), helpers.
  schema.sql       tablas (ver abajo).
  auth/            OAuth Facebook Login (facebook.py), rutas (routes.py), cifrado de
                   tokens Fernet (crypto.py), renovación del token (refresh.py).
  insights/        bajada de la Graph API: fetch.py (cliente defensivo), store.py
                   (upserts), service.py (refresh on-demand), cli.py (comandos).
  reports/         reporte de texto con Claude: generate.py (payload + prompt +
                   llamada), store.py, cli.py.
  routes/          main.py (/, /health), dashboard.py (dashboard + acciones).
  templates/       base.html, dashboard.html.
  static/          css/dashboard.css, js/dashboard.js.
tests/             pytest (mockean la red y la API de Claude; no tocan Meta).
docs/deploy.md     deploy en el VPS.
```

## Modelo de datos (SQLite, `schema.sql`)

- **`usuarias`** — OAuth: token de acceso **cifrado** (Fernet), vencimiento.
- **`account_snapshots`** — un snapshot por usuaria por día (serie de evolución):
  followers, reach, views, accounts_engaged, total_interactions, profile_views,
  website_clicks. Upsert por `(user_id, snapshot_date)`.
- **`post_metrics`** — una fila por post (upsert por `media_id`): likes,
  comments, reach, views, saved, shares, total_interactions, y watch-time de
  Reels (`avg_watch_time_ms`, `video_view_total_time_ms`).
- **`audience_demographics`** — "foto actual" (se reemplaza): breakdown
  (gender/age/country/city) × bucket × value.
- **`reports`** — historial de reportes de texto generados.

`init-db` aplica el schema **y** migraciones de columnas idempotentes
(`_COLUMN_MIGRATIONS` + `ALTER TABLE`), así que es **parte estándar del
re-deploy** cuando una release agrega columnas.

## Puesta en marcha (dev)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # completar SECRET_KEY y TOKEN_ENCRYPTION_KEY
flask init-db
python wsgi.py              # http://localhost:5000  (/health -> {"status":"ok"})
pytest                      # 182 tests
```

OAuth con Meta exige HTTPS → en dev se usa un túnel ngrok con dev-domain fijo
(`REDIRECT_URI` debe coincidir EXACTO con el registrado en la app de Meta).

### Variables de entorno (todas por env; nada se versiona)

`SECRET_KEY`*, `TOKEN_ENCRYPTION_KEY`* (Fernet), `FACEBOOK_APP_ID/SECRET`,
`REDIRECT_URI`, `GRAPH_API_VERSION` (ej. `v23.0`), `DATABASE`,
`SESSION_COOKIE_SECURE`, `ANTHROPIC_API_KEY` (reporte), `REPORT_MODEL`
(default `claude-haiku-4-5`). (* obligatorias: la app no arranca sin ellas.)

## Comandos CLI (`flask …`)

| Comando | Qué hace | Cron |
|---|---|---|
| `init-db` | crea/migra tablas (idempotente) | — |
| `refresh-tokens` | renueva el token largo si está por vencer | diario |
| `daily-snapshot` | snapshot de cuenta del día (liviano, sin posts) | diario |
| `fetch-insights` | bajada COMPLETA (snapshot + todos los posts) | manual |
| `fetch-demographics` | demografía agregada ("foto actual") | semanal |
| `generate-monthly-report` | reporte de texto del mes anterior (Claude) | mensual |

Rutas web: `/auth/login`·`/auth/callback`·`/auth/logout`, `/dashboard`,
`POST /actualizar` (refresca snapshot+demografía a pedido),
`POST /reporte` (genera reporte a pedido), `/health`, `/` (redirige al dashboard).

## Flujo de trabajo (no negociable)

**Nunca commitear directo a `main`.** Cada cambio: rama → commits **firmados**
(`git commit -S`, vía Bitwarden SSH agent) → para código sustancial, 3 gates
internos como subagentes (revisión / seguridad / datos) → PR → review de
CodeRabbit + CodeQL + CI (pytest 3.10/3.12) → **squash merge** → deploy.

- TDD: rojo → verde. Tests mockean la red (Meta) y la API de Claude.
- Cambios visuales: verificar de verdad con un preview a ancho mobile (ver
  `fix/mobile-charts` / `fix/mobile-demografia` como referencia), no a ojo.
- Antes de mutaciones en servicios externos (gh merge, VPS, etc.): confirmación
  explícita por acción.

## Gotchas (cosas que sorprenden)

- **Demografía de Meta nunca suma el total de seguidores** — se calcula sobre
  una "base demografiable" (subconjunto), y es muy sensible a la frescura. No es
  un bug. (Ver memoria de proyecto.)
- **La Graph API expone solo un subconjunto de posts** (`media_count` < lo que
  muestra la UI de IG): stories, colabs y contenido pre-Business no salen.
- **`online_followers` viene vacío** para esta cuenta → "mejor día/horario"
  está bloqueado por Meta (en BACKLOG).
- **Métricas de Reels** solo se piden para `media_type == "VIDEO"` (Meta las
  rechaza en IMAGE/CAROUSEL).
- **sqlite + `DATE`**: con `PARSE_DECLTYPES`, `snapshot_date` vuelve como
  `datetime.date`; al serializar a JSON normalizarlo a string ISO.
- **Chart.js**: `maintainAspectRatio:false` **requiere** un contenedor de altura
  fija (`.chart-box`), si no crece sin límite. Todas las charts con esa opción
  lo tienen.
- **Reporte mensual**: hoy usa los datos ACTUALES, no un agregado acotado al mes
  (en BACKLOG).

## Estado

Todo lo de las fases (scaffolding, OAuth, insights, dashboard, deploy,
demografía, renovación/snapshots, reporte de texto, métricas ampliadas, gráficos
de evolución) está **en producción**. Pendientes (no urgentes) en
[BACKLOG.md](BACKLOG.md); el único bloqueado por Meta es "mejor día/horario".
