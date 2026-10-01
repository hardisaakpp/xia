"""Recuperación híbrida: vectores (significado) + texto completo (términos exactos), fusionados con RRF.

Los vectores fallan con códigos y nombres exactos ("ST", "ITR", "INV-0042"); el texto completo falla con
paráfrasis. Cada uno cubre el punto ciego del otro.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from pgvector import Vector

from xia import db
from xia.config import get_settings

_PALABRA = re.compile(r"\w+", re.UNICODE)
_CANDIDATOS = 30
_RRF_K = 60
# Identificadores (números de migración, códigos, nombres como `estado_id`) que, si aparecen en pocos fragmentos, son
# la mejor pista que hay: se garantizan hasta _EXACTOS fragmentos que los contengan. Si aparecen en muchos (un año,
# "2026"), no discriminan y se ignoran.
_EXACTOS = 2
_MAX_COINCIDENCIAS_EXACTAS = 15


@dataclass(frozen=True)
class Recuperado:
    id: int
    area: str
    ruta: str
    titulo: str
    encabezados: str
    texto: str
    similitud: float


_SQL = """
WITH vec AS (
    SELECT id, row_number() OVER (ORDER BY embedding <=> %(q)s) AS rk
    FROM fragmentos WHERE area = ANY(%(areas)s) AND (%(docs)s::bigint[] IS NULL OR documento_id = ANY(%(docs)s))
    ORDER BY embedding <=> %(q)s LIMIT %(n)s
), txt AS (
    SELECT f.id, row_number() OVER (ORDER BY ts_rank_cd(f.tsv, query) DESC) AS rk
    FROM fragmentos f, to_tsquery('spanish', %(tsq)s) query
    WHERE f.area = ANY(%(areas)s) AND (%(docs)s::bigint[] IS NULL OR f.documento_id = ANY(%(docs)s)) AND f.tsv @@ query
    ORDER BY ts_rank_cd(f.tsv, query) DESC LIMIT %(n)s
)
SELECT f.id, f.area, d.ruta, d.titulo, f.encabezados, f.texto,
       1 - (f.embedding <=> %(q)s) AS similitud,
       COALESCE(1.0 / (%(k)s + v.rk), 0) + COALESCE(1.0 / (%(k)s + t.rk), 0) AS rrf
FROM fragmentos f
JOIN documentos d ON d.id = f.documento_id
LEFT JOIN vec v ON v.id = f.id
LEFT JOIN txt t ON t.id = f.id
WHERE v.id IS NOT NULL OR t.id IS NOT NULL OR f.id = ANY(%(ex)s)
-- Entran siempre: (1) los fragmentos con el identificador exacto de la pregunta y (2) los mejores resultados vectoriales.
-- La búsqueda por texto (OR de palabras sueltas) es ruidosa y, fusionada por RRF, desplaza al fragmento que el
-- embedding o el identificador señalan.
ORDER BY (f.id = ANY(%(ex)s)) DESC, (COALESCE(v.rk, 1000) <= %(g)s) DESC, rrf DESC
LIMIT %(top)s
"""


def _consulta_texto(pregunta: str) -> str:
    """OR de las palabras de la pregunta: to_tsquery ya descarta las vacías del español ('de', 'el', ...)."""
    palabras = {p.lower() for p in _PALABRA.findall(pregunta) if len(p) > 2}
    return " | ".join(sorted(palabras)) or "''"


def tokens_exactos(pregunta: str) -> list[str]:
    """Palabras que parecen identificadores: llevan un dígito o un guion bajo (665, estado_id, 24712, p12)."""
    return sorted({p.lower() for p in _PALABRA.findall(pregunta) if any(c.isdigit() or c == "_" for c in p)})


def _fragmentos_con_identificador(conn, pregunta: str, areas: list[str], docs: list[int] | None) -> list[int]:
    """Hasta _EXACTOS ids de fragmentos que contienen TODOS los identificadores de la pregunta; [] si no hay o si
    son tan comunes que no sirven para distinguir."""
    tokens = tokens_exactos(pregunta)
    if not tokens:
        return []
    ids = [r[0] for r in conn.execute(
        "SELECT f.id FROM fragmentos f, to_tsquery('spanish', %(q)s) query "
        "WHERE f.area = ANY(%(areas)s) AND (%(docs)s::bigint[] IS NULL OR f.documento_id = ANY(%(docs)s)) "
        "AND f.tsv @@ query ORDER BY ts_rank_cd(f.tsv, query) DESC LIMIT %(lim)s",
        {"q": " & ".join(tokens), "areas": areas, "docs": docs, "lim": _MAX_COINCIDENCIAS_EXACTAS + 1},
    ).fetchall()]
    return ids[:_EXACTOS] if 0 < len(ids) <= _MAX_COINCIDENCIAS_EXACTAS else []


def recuperar(pregunta: str, vector: list[float], areas: list[str], limite: int | None = None,
              documentos: list[int] | None = None) -> list[Recuperado]:
    """`documentos`: ids que el usuario puede ver (None = todos). Se filtra en SQL: lo no permitido nunca sale de la BD."""
    s = get_settings()
    with db.pool().connection() as conn:
        exactos = _fragmentos_con_identificador(conn, pregunta, areas, documentos)
        filas = conn.execute(
            _SQL,
            {"q": Vector(vector), "areas": areas, "docs": documentos, "tsq": _consulta_texto(pregunta), "ex": exactos,
             "n": _CANDIDATOS, "k": _RRF_K, "top": limite or s.top_k, "g": s.vectoriales_garantizados},
        ).fetchall()
    return [Recuperado(*fila[:7]) for fila in filas]
