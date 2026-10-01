"""Reranker (cross-encoder): reordena los candidatos de la búsqueda con un modelo que lee pregunta y fragmento JUNTOS.

El embedding compara dos vectores calculados por separado (rápido, pero grueso); el cross-encoder evalúa cada par
pregunta-fragmento con atención conjunta (más preciso, más lento). Por eso se aplica solo a unas decenas de candidatos.

Dependencias opcionales: `pip install .[rerank]` (más PyTorch; en CPU alcanza: `--index-url .../whl/cpu`).
"""
from __future__ import annotations

import threading
from functools import lru_cache

from xia.config import get_settings
from xia.retrieval import Recuperado

_MAX_TOKENS = 512
_candado = threading.Lock()  # el modelo no se comparte entre hilos de forma segura


@lru_cache(maxsize=1)
def _modelo():
    from sentence_transformers import CrossEncoder

    return CrossEncoder(get_settings().modelo_reranker, max_length=_MAX_TOKENS)


def reordenar(pregunta: str, candidatos: list[Recuperado]) -> list[Recuperado]:
    """Candidatos de más a menos relevante para la pregunta."""
    if len(candidatos) < 2:
        return candidatos
    pares = [(pregunta, f"{c.encabezados}\n\n{c.texto}") for c in candidatos]
    with _candado:
        puntajes = _modelo().predict(pares, batch_size=8, show_progress_bar=False)
    orden = sorted(range(len(candidatos)), key=lambda i: -float(puntajes[i]))
    return [candidatos[i] for i in orden]
