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
