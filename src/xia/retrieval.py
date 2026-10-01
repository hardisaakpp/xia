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
    FROM fragmentos WHERE area = ANY(%(areas)s)
    ORDER BY embedding <=> %(q)s LIMIT %(n)s
), txt AS (
    SELECT f.id, row_number() OVER (ORDER BY ts_rank_cd(f.tsv, query) DESC) AS rk
    FROM fragmentos f, to_tsquery('spanish', %(tsq)s) query
    WHERE f.area = ANY(%(areas)s) AND f.tsv @@ query
    ORDER BY ts_rank_cd(f.tsv, query) DESC LIMIT %(n)s
)
SELECT f.id, f.area, d.ruta, d.titulo, f.encabezados, f.texto,
       1 - (f.embedding <=> %(q)s) AS similitud,
       COALESCE(1.0 / (%(k)s + v.rk), 0) + COALESCE(1.0 / (%(k)s + t.rk), 0) AS rrf
FROM fragmentos f
JOIN documentos d ON d.id = f.documento_id
LEFT JOIN vec v ON v.id = f.id
LEFT JOIN txt t ON t.id = f.id
WHERE v.id IS NOT NULL OR t.id IS NOT NULL
ORDER BY rrf DESC
LIMIT %(top)s
"""


def _consulta_texto(pregunta: str) -> str:
    """OR de las palabras de la pregunta: to_tsquery ya descarta las vacías del español ('de', 'el', ...)."""
    palabras = {p.lower() for p in _PALABRA.findall(pregunta) if len(p) > 2}
    return " | ".join(sorted(palabras)) or "''"


def recuperar(pregunta: str, vector: list[float], areas: list[str]) -> list[Recuperado]:
    s = get_settings()
    with db.pool().connection() as conn:
        filas = conn.execute(
            _SQL,
            {"q": Vector(vector), "areas": areas, "tsq": _consulta_texto(pregunta),
             "n": _CANDIDATOS, "k": _RRF_K, "top": s.top_k},
        ).fetchall()
    return [Recuperado(*fila[:7]) for fila in filas]
