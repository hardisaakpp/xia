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
from pydantic import BaseModel, Field, field_validator, model_validator

from xia import acceso, agente, cuota, db, intencion, servicio
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


_NOMBRE_HERRAMIENTA = r"^[A-Za-z_][A-Za-z0-9_]{0,63}$"


class LlamadaIn(BaseModel):
    nombre: str = Field(pattern=_NOMBRE_HERRAMIENTA)
    argumentos: dict[str, Any] = Field(default_factory=dict)


class MensajeAgenteIn(BaseModel):
    rol: Literal["user", "assistant", "tool"]
    texto: str = Field(default="", max_length=12000)
    llamadas: list[LlamadaIn] | None = Field(default=None, max_length=8)  # solo en mensajes del asistente
    herramienta: str | None = Field(default=None, pattern=_NOMBRE_HERRAMIENTA)  # solo en resultados de herramienta


class HerramientaIn(BaseModel):
    nombre: str = Field(pattern=_NOMBRE_HERRAMIENTA)
    descripcion: str = Field(default="", max_length=800)
    parametros: dict[str, Any] | None = None

    @field_validator("nombre")
    @classmethod
    def _no_reservada(cls, v: str) -> str:
        if v == agente.HERRAMIENTA_DOCUMENTACION:
            raise ValueError("nombre reservado: es una herramienta propia de Xia")
        return v


class AgenteIn(BaseModel):
    """Un paso de la conversación con herramientas. Sin estado: el cliente envía todo lo necesario cada vez."""
    mensajes: list[MensajeAgenteIn] = Field(min_length=1, max_length=40)
    herramientas: list[HerramientaIn] = Field(default_factory=list, max_length=12)
    # Reglas propias de la aplicación (confiables: las pone ella, no la persona). Se añaden a las de Xia.
    instrucciones: str | None = Field(default=None, max_length=2000)
    idioma: Literal["es", "en"] = "es"

    @model_validator(mode="after")
    def _termina_en_persona_o_resultado(self) -> "AgenteIn":
        if self.mensajes[-1].rol == "assistant":
            raise ValueError("el último mensaje debe ser de la persona o un resultado de herramienta")
        return self


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


@app.post("/v1/agente")
def agente_paso(cuerpo: AgenteIn, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """Un paso del agente: responde, o pide que la aplicación ejecute herramientas y vuelva con los resultados."""
    identidad = acceso.identificar(authorization, None)
    return servicio.responder_agente(identidad, [m.model_dump() for m in cuerpo.mensajes],
                                     [h.model_dump() for h in cuerpo.herramientas], cuerpo.instrucciones, cuerpo.idioma)


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
