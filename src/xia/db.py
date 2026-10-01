from __future__ import annotations

import psycopg
from pgvector.psycopg import register_vector
from psycopg_pool import ConnectionPool

from xia.config import get_settings

_ESQUEMA = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS areas (
    codigo      text PRIMARY KEY,
    nombre      text NOT NULL,
    descripcion text
);

CREATE TABLE IF NOT EXISTS documentos (
    id          bigserial PRIMARY KEY,
    area        text NOT NULL REFERENCES areas(codigo) ON DELETE CASCADE,
    ruta        text NOT NULL,
    titulo      text NOT NULL,
    hash        text NOT NULL,
    actualizado timestamptz NOT NULL DEFAULT now(),
    UNIQUE (area, ruta)
);

CREATE TABLE IF NOT EXISTS fragmentos (
    id           bigserial PRIMARY KEY,
    documento_id bigint NOT NULL REFERENCES documentos(id) ON DELETE CASCADE,
    area         text NOT NULL,
    orden        int NOT NULL,
    encabezados  text NOT NULL DEFAULT '',
    texto        text NOT NULL,
    embedding    vector({dim}) NOT NULL,
    tsv          tsvector GENERATED ALWAYS AS (to_tsvector('spanish', encabezados || ' ' || texto)) STORED
);
CREATE INDEX IF NOT EXISTS fragmentos_area_idx ON fragmentos (area);
CREATE INDEX IF NOT EXISTS fragmentos_tsv_idx ON fragmentos USING gin (tsv);
CREATE INDEX IF NOT EXISTS fragmentos_emb_idx ON fragmentos USING hnsw (embedding vector_cosine_ops);

-- Auditoría y base de la cuota (las consultas con error no cuentan).
CREATE TABLE IF NOT EXISTS consultas (
    traza_id      uuid PRIMARY KEY,
    usuario_ad    text NOT NULL,
    pregunta      text NOT NULL,
    areas         text[] NOT NULL,
    modelo        text,
    ms            int,
    sin_contexto  boolean,
    fragmentos_ids bigint[],
    error         text,
    creada        timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE consultas ADD COLUMN IF NOT EXISTS pregunta_reformulada text;
CREATE INDEX IF NOT EXISTS consultas_usuario_idx ON consultas (usuario_ad, creada);
"""

_pool: ConnectionPool | None = None


def iniciar_esquema() -> None:
    """Crea extensión y tablas si no existen (idempotente). Va antes de abrir el pool: register_vector necesita la extensión."""
    s = get_settings()
    with psycopg.connect(s.database_url, autocommit=True) as conn:
        conn.execute(_ESQUEMA.format(dim=s.dim_embeddings))


def pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            get_settings().database_url,
            min_size=1,
            max_size=8,
            configure=register_vector,
            open=True,
        )
    return _pool


def cerrar_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None
