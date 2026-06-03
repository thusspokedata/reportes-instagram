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
