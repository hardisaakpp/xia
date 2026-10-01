"""Orquesta una consulta completa: cuota → pipeline → auditoría. La API solo traduce HTTP."""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from xia import acceso, cuota, db, pipeline
from xia.errores import XiaError

log = logging.getLogger("xia.servicio")


def _auditar(traza: str, usuario_ad: str, pregunta: str, areas: list[str], *, modelo: str | None = None,
             ms: int | None = None, sin_contexto: bool | None = None, ids: list[int] | None = None,
             reformulada: str | None = None, intencion: str | None = None, error: str | None = None) -> None:
    with db.pool().connection() as conn:
        conn.execute(
            "INSERT INTO consultas (traza_id, usuario_ad, pregunta, areas, modelo, ms, sin_contexto, fragmentos_ids, "
            "pregunta_reformulada, intencion, error) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (traza, usuario_ad, pregunta, areas, modelo, ms, sin_contexto, ids, reformulada, intencion, error),
        )


def responder(identidad: acceso.Identidad, pregunta: str, areas: list[str] | None,
              historial: list[dict[str, str]] | None = None) -> dict[str, Any]:
    usuario_ad = identidad.usuario
    traza = str(uuid.uuid4())
    inicio = time.perf_counter()

    estado = cuota.consultar(usuario_ad)
    if estado["restantes"] <= 0:
        err = XiaError("cuota-agotada",
                       "Alcanzaste tu límite de consultas por ahora. Se renueva automáticamente en unas horas.",
                       429, cuota=estado)
        err.traza_id = traza
        _auditar(traza, usuario_ad, pregunta, areas or [], error=err.codigo)
        raise err

    try:
        r = pipeline.ejecutar(pregunta, areas, historial=historial, alcance=acceso.alcance(identidad))
    except XiaError as e:
        e.traza_id = traza
        _auditar(traza, usuario_ad, pregunta, areas or [], error=e.codigo)
        raise

    ms = int((time.perf_counter() - inicio) * 1000)
    _auditar(traza, usuario_ad, pregunta, r.areas_consultadas, modelo=r.modelo, ms=ms,
             sin_contexto=r.sin_contexto, ids=r.fragmentos_ids,
             reformulada=r.pregunta_efectiva if r.pregunta_efectiva != pregunta else None, intencion=r.intencion)
    log.info("traza=%s usuario=%s ms=%d sin_contexto=%s sim=%.3f", traza, usuario_ad, ms, r.sin_contexto, r.mejor_similitud)

    return {
        "respuesta": r.respuesta,
        "fuentes": r.fuentes,
        "sin_contexto": r.sin_contexto,
        "areas_consultadas": r.areas_consultadas,
        "modelo": r.modelo,
        "ms": ms,
        "traza_id": traza,
        "cuota": cuota.consultar(usuario_ad),
    }
