"""API HTTP de Xia. Contrato compatible con mIA (ver web-scnexus/src/services/miaApi.ts):
los errores se deciden por el campo `error`, no por el status."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, Literal

import psycopg
from fastapi import FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from xia import acceso, cuota, db, intencion, servicio
from xia.errores import XiaError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    acceso.validar_configuracion()
    db.iniciar_esquema()
    db.pool()
    try:
        intencion.precalentar()  # si Ollama aún no está, se calcula en la primera consulta
    except Exception:  # noqa: BLE001
        logging.getLogger("xia.api").warning("No se pudo precalentar la detección de charla")
    yield
    db.cerrar_pool()


app = FastAPI(title="Xia", version="0.1.0", lifespan=lifespan)


class Turno(BaseModel):
    rol: Literal["user", "bot"]
    texto: str = Field(max_length=4000)


class PreguntaIn(BaseModel):
    # Solo se usa con XIA_AUTENTICACION=ninguna (desarrollo). Con JWT, el usuario sale del token: este campo se ignora.
    usuario_ad: str | None = Field(default=None, max_length=100)
    pregunta: str = Field(min_length=1, max_length=1000)
    areas: list[str] | None = None
    # Conversación previa (sin incluir la pregunta actual), la más antigua primero. Opcional: sin ella, cada
    # pregunta se trata sola. Solo se usan los últimos turnos; el cliente puede mandar menos de 10.
    historial: list[Turno] | None = Field(default=None, max_length=10)
    # Idioma en que se redacta la respuesta generada (los mensajes fijos del servicio siguen en español).
    idioma: Literal["es", "en"] = "es"


@app.exception_handler(XiaError)
async def _xia_error(_: Request, e: XiaError) -> JSONResponse:
    headers = {"Retry-After": str(e.reintentar_en_segundos)} if e.reintentar_en_segundos is not None else None
    return JSONResponse(e.cuerpo(), status_code=e.status, headers=headers)


@app.exception_handler(RequestValidationError)
async def _validacion(_: Request, e: RequestValidationError) -> JSONResponse:
    detalles = [{"campo": ".".join(str(p) for p in err["loc"][1:]) or "cuerpo", "motivo": err["msg"]} for err in e.errors()]
    return JSONResponse(XiaError("peticion-invalida", "La petición no es válida.", 400, detalles=detalles).cuerpo(),
                        status_code=400)


@app.exception_handler(psycopg.OperationalError)
async def _bd_caida(_: Request, e: psycopg.OperationalError) -> JSONResponse:
    logging.getLogger("xia.api").error("BD no disponible: %s", e)
    err = XiaError("sin-indice", "La base de conocimiento no está disponible. Ya se puede reportar al equipo de TI.", 503)
    return JSONResponse(err.cuerpo(), status_code=503)


@app.exception_handler(Exception)
async def _inesperado(_: Request, e: Exception) -> JSONResponse:
    logging.getLogger("xia.api").exception("Error no controlado")
    err = XiaError("error-interno", "Ocurrió un error inesperado en el asistente.", 500)
    return JSONResponse(err.cuerpo(), status_code=500)


@app.post("/v1/preguntar")
def preguntar(cuerpo: PreguntaIn, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    # `def` (no `async`): corre en el threadpool, porque Ollama y la BD se llaman de forma bloqueante.
    historial = [t.model_dump() for t in cuerpo.historial] if cuerpo.historial else None
    identidad = acceso.identificar(authorization, cuerpo.usuario_ad)
    return servicio.responder(identidad, cuerpo.pregunta.strip(), cuerpo.areas, historial, cuerpo.idioma)


@app.get("/v1/cuota")
def obtener_cuota(usuario_ad: str | None = None, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    return cuota.consultar(acceso.identificar(authorization, usuario_ad).usuario)


@app.get("/v1/areas")
def areas(usuario_ad: str | None = None, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """Solo las áreas que el usuario puede ver."""
    visibles = acceso.alcance(acceso.identificar(authorization, usuario_ad)).areas
    with db.pool().connection() as conn:
        filas = conn.execute(
            "SELECT a.codigo, EXISTS (SELECT 1 FROM fragmentos f WHERE f.area = a.codigo) FROM areas a ORDER BY a.codigo"
        ).fetchall()
    return {"areas": [{"codigo": c, "con_documentos": d} for c, d in filas if c in visibles]}


@app.get("/v1/salud")
def salud() -> dict[str, bool]:
    with db.pool().connection() as conn:
        conn.execute("SELECT 1")
    return {"ok": True}
