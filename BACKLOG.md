# Backlog

Mejoras y deuda técnica anotadas para próximas iteraciones. No bloquean nada
hoy; se priorizan cuando corresponda. Cada ítem indica su origen.

## Dashboard

- **Desambiguar etiquetas de posts del mismo día en los gráficos.**
  En "Engagement por post" y "Reach por post" el eje X usa solo la fecha
  (`YYYY-MM-DD`), así que dos posts del mismo día comparten etiqueta (ej. dos
  `2026-05-28`). Mejorar el label para distinguirlos: fecha + hora, o un índice
  por día (`28-05 #1`, `28-05 #2`), o un identificador corto del post.
  - Archivo: `app/routes/dashboard.py` (`_post_label`).
  - Origen: SPEC 04 (observado al revisar el gráfico real).
  - Esfuerzo: bajo.

## Reportes (Claude API)

- **Rate-limit / debounce de los botones de acción.**
  Dos POST disparan operaciones con costo por cada click, sin límite:
  `/reporte` (llamada paga a la API de Claude) y `/actualizar` (~8 llamadas a
  Meta para snapshot + demografía). Una usuaria autenticada podría martillarlos
  y gastar tokens / agotar el rate limit de Meta (~200/h, que también usa el
  cron). Agregar un guard simple (p. ej. cooldown por usuaria, o no actualizar
  si ya hay snapshot del día). Riesgo acotado: app privada, exige sesión.
  - Archivos: `app/routes/dashboard.py` (`generar_reporte`, `actualizar_datos`).
  - Origen: SPEC 07 + "Actualizar datos" (gates de seguridad, OBSERVACIÓN-2).
  - Esfuerzo: bajo.

- **Refresh on-demand: persistencia no transaccional.**
  `refresh_account_data` commitea el snapshot antes de bajar la demografía; si la
  demografía falla a mitad, el snapshot ya quedó persistido (parcial). No es un
  problema real (cada parte es idempotente y el snapshot es el dato crítico),
  pero queda anotado. Consistente con el patrón actual del proyecto.
  - Archivo: `app/insights/service.py` (`refresh_account_data`).
  - Origen: "Actualizar datos" (gate de datos, OBSERVACIÓN).
  - Esfuerzo: bajo.

- **Unificar la lectura de métricas de la usuaria (dedup de queries).**
  Las tres queries (snapshot + posts + demografía) se repiten textualmente entre
  `app/routes/dashboard.py` (ruta `dashboard`) y
  `app/reports/generate.py` (`generate_and_save_report`). Extraer un helper
  compartido (`load_user_metrics(db, user_id)`) para que no diverjan — las
  consultas cargan justo las columnas que alimentan los guardrails.
  - Origen: SPEC 07 (revisión interna, M3).
  - Esfuerzo: bajo.

- **El reporte mensual usa datos ACTUALES, no del mes etiquetado.**
  `generate-monthly-report` arma el texto con `build_report_input`, que lee el
  estado actual de la base (snapshot de hoy + todos los posts + demografía
  actual), no un agregado acotado al mes. O sea, el reporte "2026-05" describe
  la foto del día en que corre, no la actividad de mayo. Funciona como foto de
  cadencia mensual, pero para un análisis realmente del mes haría falta:
  filtrar posts por rango de fechas, calcular el crecimiento del mes desde la
  serie de `account_snapshots`, y pasarle esa serie al modelo.
  - Archivo: `app/reports/generate.py` (`build_report_input`).
  - Origen: SPEC 07 (verificación en producción).
  - Esfuerzo: medio.

- **"Mejor día/horario para publicar" — bloqueado por datos de Meta.**
  El insight `online_followers` (seguidores online por hora) responde pero viene
  VACÍO (`value: {}`) para esta cuenta — Meta no da la distribución horaria
  (depende del tamaño de audiencia). Y con ~12 posts, inferir el horario desde
  los propios posts sería poco confiable (N chico). Revisar cuando la cuenta
  crezca. Alternativa futura: `reached_audience_demographics` /
  `engaged_audience_demographics` (requieren parámetro `timeframe`).
  - Origen: SPEC "más métricas" (sonda contra la cuenta real).
  - Esfuerzo: medio (cuando haya datos).

## Plataforma / deuda técnica

- **Converters deprecados de sqlite3 (Python 3.12).**
  La suite emite `DeprecationWarning` porque sqlite3 deprecó los converters por
  defecto de `TIMESTAMP`/`DATE` (`detect_types=PARSE_DECLTYPES` en `app/db.py`).
  Registrar converters propios siguiendo las recetas de la doc para evitar la
  futura rotura. (Ya existe un chip/sesión para esto.)
  - Esfuerzo: bajo-medio.

## Datos / Meta (informativo, no es bug)

- **La Graph API expone 10 de 13 posts (`media_count = 10`).**
  El perfil de IG muestra 13 pero la API reporta y devuelve 10 (consistente
  entre `media_count` y la lista). Los 3 faltantes son contenido que Meta no
  expone por la API (stories, colaboraciones donde no se es owner, o media
  previa a la cuenta Business). Documentado para no confundirlo con un bug de
  paginación. Si en el futuro se necesitan esos 3, investigar si hay algún
  endpoint/permiso que los exponga (puede no existir).
  - Origen: SPEC 03b.
