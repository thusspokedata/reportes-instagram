-- Esquema de datos. Simple y extensible: en specs posteriores se suman
-- tablas de snapshots de métricas que referenciarán a `usuarias`.

CREATE TABLE IF NOT EXISTS usuarias (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    fb_user_id            TEXT NOT NULL UNIQUE,   -- identificador de Meta
    nombre                TEXT,                   -- lo que devuelva Meta
    access_token_cifrado  TEXT NOT NULL,          -- token largo, cifrado (Fernet)
    token_expira_en       TIMESTAMP,              -- vencimiento del token largo
    creado_en             TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actualizado_en        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Snapshot diario de métricas de CUENTA. Una fila por usuaria por día.
-- Tabla "wide" (columnas fijas) para que la fase de gráficos lea series
-- temporales directo, sin pivotear. Métricas nullable: ausente = NULL (no 0).
CREATE TABLE IF NOT EXISTS account_snapshots (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id             INTEGER NOT NULL,           -- FK -> usuarias.id
    snapshot_date       DATE    NOT NULL,           -- día del snapshot (YYYY-MM-DD)
    views               INTEGER,                    -- métricas de cuenta de Meta;
    reach               INTEGER,                    --   NULL si Meta no la devolvió
    follower_count      INTEGER,                    --   NULL si <100 seguidores
    reposts             INTEGER,
    accounts_engaged    INTEGER,
    total_interactions  INTEGER,
    creado_en           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actualizado_en      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES usuarias(id) ON DELETE CASCADE
);

-- Un snapshot por usuaria por día; el índice cubre la query de gráficos
-- (WHERE user_id = ? ORDER BY snapshot_date).
CREATE UNIQUE INDEX IF NOT EXISTS idx_account_snapshots_user_date
    ON account_snapshots (user_id, snapshot_date);

-- Métricas por POST. Una fila por (usuaria, media_id de Meta). No es serie
-- temporal: se upsertea al re-bajar. Métricas nullable: ausente = NULL.
CREATE TABLE IF NOT EXISTS post_metrics (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id             INTEGER NOT NULL,           -- FK -> usuarias.id
    media_id            TEXT    NOT NULL,           -- id del media en Meta
    media_type          TEXT,                       -- IMAGE / CAROUSEL_ALBUM / VIDEO...
    permalink           TEXT,                       -- URL pública del post
    caption             TEXT,                       -- texto del post
    -- Fecha de publicación tal cual la manda Meta (ISO-8601 con offset, ej.
    -- 2026-06-01T00:00:00+0000). Se guarda como TEXT: el formato de Meta no es
    -- compatible con el converter TIMESTAMP de sqlite; la fase de gráficos lo
    -- parsea explícitamente.
    timestamp           TEXT,                       -- cuándo se publicó (de Meta)
    reach               INTEGER,                    -- métricas del post; NULL si ausente
    views               INTEGER,
    likes               INTEGER,
    comments            INTEGER,
    saved               INTEGER,
    shares              INTEGER,
    total_interactions  INTEGER,
    fetched_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,  -- última bajada
    creado_en           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actualizado_en      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES usuarias(id) ON DELETE CASCADE
);

-- Un registro por post por usuaria; soporta el upsert al re-bajar métricas.
CREATE UNIQUE INDEX IF NOT EXISTS idx_post_metrics_user_media
    ON post_metrics (user_id, media_id);
