"""Pipeline de consulta (nivel 1): embeber pregunta → recuperar → decidir si hay contexto → generar → citar."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from xia import db
from xia.config import get_settings
from xia.errores import XiaError
from xia.llm import embeber, generar
from xia.retrieval import Recuperado, recuperar

MARCA_SIN_INFO = "NO_HAY_INFORMACION"
MENSAJE_SIN_CONTEXTO = "No encontré información sobre eso en la documentación disponible."

_SISTEMA = f"""Eres Xia, el asistente de SCNEXUS. Respondes preguntas usando ÚNICAMENTE los fragmentos de documentación que se te entregan.

Reglas:
- Si los fragmentos no contienen la respuesta, responde exactamente: {MARCA_SIN_INFO}
- No inventes datos, pasos, nombres de endpoints, estados ni valores que no estén en los fragmentos.
- Responde en español, de forma clara y breve.
- Al final de cada afirmación indica el número del fragmento que la respalda, así: [1] o [2][3]."""

_CITA = re.compile(r"\[(\d+)\]")
# Los modelos escriben la marca con tilde, en minúsculas o con espacios en vez de guion bajo.
_SIN_INFO = re.compile(r"NO[_ ]HAY[_ ]INFORMACI[OÓ]N", re.IGNORECASE)


@dataclass
class Resultado:
    respuesta: str
    fuentes: list[dict[str, str]]
    sin_contexto: bool
    areas_consultadas: list[str]
    modelo: str
    fragmentos_ids: list[int] = field(default_factory=list)
    mejor_similitud: float = 0.0
    documentos_recuperados: list[str] = field(default_factory=list)  # para evaluar la recuperación aparte de la generación


def resolver_areas(solicitadas: list[str] | None) -> list[str]:
    """Áreas que tienen documentos. Si el usuario eligió, deben existir en el catálogo."""
    with db.pool().connection() as conn:
        catalogo = {r[0] for r in conn.execute("SELECT codigo FROM areas")}
        con_docs = [r[0] for r in conn.execute("SELECT DISTINCT area FROM fragmentos ORDER BY area")]
    if solicitadas:
        desconocidas = [a for a in solicitadas if a not in catalogo]
        if desconocidas:
            raise XiaError("area-no-permitida", f"Área no disponible: {', '.join(desconocidas)}.", 403)
        con_docs = [a for a in con_docs if a in solicitadas]
    if not con_docs:
        raise XiaError("sin-areas", "No hay documentación publicada para consultar todavía.", 404)
    return con_docs


def _prompt_usuario(pregunta: str, fragmentos: list[Recuperado]) -> str:
    bloques = [f"[{i}] ({f.titulo} · {f.encabezados})\n{f.texto}" for i, f in enumerate(fragmentos, 1)]
    return "Fragmentos de documentación:\n\n" + "\n\n".join(bloques) + f"\n\nPregunta: {pregunta}"


def _fuentes(fragmentos: list[Recuperado], usados: list[int]) -> list[dict[str, str]]:
    """Documentos de los fragmentos que el modelo citó; si no citó ninguno, los de todos los entregados."""
    elegidos = [fragmentos[i - 1] for i in usados if 1 <= i <= len(fragmentos)] or fragmentos
    vistos: dict[tuple[str, str], dict[str, str]] = {}
    for f in elegidos:
        vistos.setdefault((f.area, f.ruta), {"area": f.area, "documento": f.ruta, "titulo": f.titulo})
    return list(vistos.values())


def ejecutar(pregunta: str, areas: list[str] | None, modelo: str | None = None) -> Resultado:
    s = get_settings()
    modelo = modelo or s.modelo_generacion
    areas_consultadas = resolver_areas(areas)

    vector = embeber([pregunta])[0]
    fragmentos = recuperar(pregunta, vector, areas_consultadas)
    mejor = max((f.similitud for f in fragmentos), default=0.0)

    base = Resultado(MENSAJE_SIN_CONTEXTO, [], True, areas_consultadas, modelo,
                     [f.id for f in fragmentos], mejor, [f.ruta for f in fragmentos])
    if not fragmentos or mejor < s.umbral_relevancia:
        return base  # Sin contexto confiable: no se gasta una generación (ni se arriesga a inventar).

    texto = generar(
        [{"role": "system", "content": _SISTEMA}, {"role": "user", "content": _prompt_usuario(pregunta, fragmentos)}],
        modelo,
    )
    if _SIN_INFO.search(texto):
        return base

    usados = [int(n) for n in _CITA.findall(texto)]
    base.respuesta = re.sub(r"\s*\[\d+\]", "", texto).strip()  # Las marcas [n] sirven para citar, no para el usuario.
    base.fuentes = _fuentes(fragmentos, usados)
    base.sin_contexto = False
    return base
