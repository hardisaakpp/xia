"""Cliente de Ollama (embeddings y generación). Cambiar de proveedor = reemplazar este módulo."""
from __future__ import annotations

import logging
import threading
from typing import Any

import httpx

from xia.config import get_settings
from xia.errores import XiaError

log = logging.getLogger("xia.llm")

_cola = threading.BoundedSemaphore(get_settings().max_concurrentes)


def _post(ruta: str, cuerpo: dict[str, Any]) -> dict[str, Any]:
    s = get_settings()
    try:
        r = httpx.post(f"{s.ollama_url}{ruta}", json=cuerpo, timeout=s.timeout_llm_s)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPError as e:
        log.error("Ollama %s falló: %s", ruta, e)
        raise XiaError(
            "sin-modelo",
            "El motor de IA no está respondiendo en este momento. Intenta de nuevo en unos minutos.",
            503,
        ) from e


def embeber(textos: list[str]) -> list[list[float]]:
    """Un vector por texto, en el mismo orden."""
    s = get_settings()
    vectores: list[list[float]] = []
    for i in range(0, len(textos), 16):
        data = _post("/api/embed", {"model": s.modelo_embeddings, "input": textos[i : i + 16], "keep_alive": s.ollama_keep_alive})
        vectores.extend(data["embeddings"])
    return vectores


def generar(mensajes: list[dict[str, str]], modelo: str | None = None, temperatura: float = 0.1) -> str:
    s = get_settings()
    if not _cola.acquire(timeout=s.espera_cola_s):
        raise XiaError("demasiadas-peticiones", "Hay muchas consultas en curso. Intenta de nuevo en unos segundos.", 429,
                       reintentar_en_segundos=10)
    try:
        data = _post(
            "/api/chat",
            {
                "model": modelo or s.modelo_generacion,
                "messages": mensajes,
                "stream": False,
                "think": s.pensar,
                "keep_alive": s.ollama_keep_alive,
                "options": {"temperature": temperatura, "num_ctx": s.ollama_num_ctx},
            },
        )
    finally:
        _cola.release()
    return data["message"]["content"].strip()


def conversar(mensajes: list[dict[str, Any]], herramientas: list[dict[str, Any]], modelo: str | None = None,
              temperatura: float = 0.1) -> dict[str, Any]:
    """Un turno del modelo con herramientas. Devuelve el mensaje completo: `content` y, si pidió herramientas, `tool_calls`."""
    s = get_settings()
    if not _cola.acquire(timeout=s.espera_cola_s):
        raise XiaError("demasiadas-peticiones", "Hay muchas consultas en curso. Intenta de nuevo en unos segundos.", 429,
                       reintentar_en_segundos=10)
    try:
        data = _post(
            "/api/chat",
            {
                "model": modelo or s.modelo_generacion,
                "messages": mensajes,
                "tools": herramientas,
                "stream": False,
                "think": s.pensar,
                "keep_alive": s.ollama_keep_alive,
                "options": {"temperature": temperatura, "num_ctx": s.ollama_num_ctx},
            },
        )
    finally:
        _cola.release()
    return data["message"]
