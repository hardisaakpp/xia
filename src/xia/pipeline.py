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

_SISTEMA_REFORMULAR = """Reescribe la ÚLTIMA pregunta del usuario para que se entienda sola, sin necesitar la conversación previa.

Reglas:
- Si la pregunta usa referencias ("ese", "eso", "y si...", "el incidente", "el perfil"), reemplázalas por el nombre concreto al que apuntan en la conversación (estado, perfil, código, documento, proceso).
- Si la pregunta ya dice por sí misma de qué trata (nombra el estado, perfil, proceso o documento), devuélvela IGUAL, sin cambios, aunque la conversación hable de algo parecido. Nunca mezcles datos de la conversación en una pregunta que ya está completa.
- NO respondas la pregunta. NO agregues información que no esté en la conversación.
- Devuelve únicamente la pregunta reescrita, en una sola línea.

Ejemplos:

Conversación:
Usuario: ¿Qué permiso necesita el perfil Contador?
Asistente: Necesita el permiso contabilidad.view.
Última pregunta: ¿Y qué puede hacer con él?
Reescrita: ¿Qué puede hacer el perfil Contador con el permiso contabilidad.view?

Conversación:
Usuario: ¿Cómo se anula una factura?
Asistente: Desde el botón Anular del detalle de la factura.
Última pregunta: ¿Y si ya fue enviada?
Reescrita: ¿Cómo se anula una factura que ya fue enviada?

Conversación:
Usuario: ¿Cómo se anula una factura?
Asistente: Desde el botón Anular del detalle de la factura.
Última pregunta: ¿Cuál es el horario de atención?
Reescrita: ¿Cuál es el horario de atención?

Conversación:
Usuario: ¿Qué permiso necesita el perfil Contador?
Asistente: Necesita el permiso contabilidad.view.
Última pregunta: ¿Qué estado tiene una factura rechazada por el cliente?
Reescrita: ¿Qué estado tiene una factura rechazada por el cliente?"""

_TURNOS_REFORMULACION = 4  # turnos recientes que se consideran
_MAX_CHARS_TURNO = 500

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
    pregunta_efectiva: str = ""  # la que se usó para buscar: la reformulada si había historial


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


def reformular(pregunta: str, historial: list[dict[str, str]], modelo: str) -> str:
    """Convierte una pregunta de seguimiento ("¿y si falla?") en una autosuficiente para poder buscarla.

    Ante cualquier salida sospechosa (vacía, o tan larga que el modelo seguramente respondió en vez de
    reescribir) se conserva la pregunta original: peor que no reformular es buscar con texto inventado.
    """
    turnos = historial[-_TURNOS_REFORMULACION:]
    conversacion = "\n".join(
        f"{'Usuario' if t['rol'] == 'user' else 'Asistente'}: {t['texto'][:_MAX_CHARS_TURNO]}" for t in turnos
    )
    salida = generar(
        [{"role": "system", "content": _SISTEMA_REFORMULAR},
         {"role": "user", "content": f"Conversación:\n{conversacion}\n\nÚltima pregunta: {pregunta}"}],
        modelo,
    )
    lineas = salida.strip().strip('"“”').splitlines()
    reescrita = lineas[0].strip().strip('"“”') if lineas else ""
    if not reescrita or len(reescrita) > max(300, 3 * len(pregunta)):
        return pregunta
    return reescrita


def buscar(pregunta: str, areas: list[str]) -> list[Recuperado]:
    """Fragmentos más relevantes: búsqueda híbrida y, si está activado, reordenados por un reranker."""
    s = get_settings()
    vector = embeber([pregunta])[0]
    if s.reranker == "ninguno":
        return recuperar(pregunta, vector, areas)
    from xia.rerank import reordenar  # import perezoso: el reranker trae dependencias pesadas y es opcional

    candidatos = recuperar(pregunta, vector, areas, limite=s.candidatos_rerank)
    return reordenar(pregunta, candidatos)[: s.top_k]


def ejecutar(pregunta: str, areas: list[str] | None, modelo: str | None = None,
             historial: list[dict[str, str]] | None = None) -> Resultado:
    s = get_settings()
    modelo = modelo or s.modelo_generacion
    areas_consultadas = resolver_areas(areas)

    # Sin historial no se paga la llamada extra al modelo.
    efectiva = reformular(pregunta, historial, modelo) if historial else pregunta
    fragmentos = buscar(efectiva, areas_consultadas)
    mejor = max((f.similitud for f in fragmentos), default=0.0)

    base = Resultado(MENSAJE_SIN_CONTEXTO, [], True, areas_consultadas, modelo,
                     [f.id for f in fragmentos], mejor, [f.ruta for f in fragmentos], efectiva)
    if not fragmentos or mejor < s.umbral_relevancia:
        return base  # Sin contexto confiable: no se gasta una generación (ni se arriesga a inventar).

    texto = generar(
        [{"role": "system", "content": _SISTEMA}, {"role": "user", "content": _prompt_usuario(efectiva, fragmentos)}],
        modelo,
    )
    if _SIN_INFO.search(texto):
        return base

    usados = [int(n) for n in _CITA.findall(texto)]
    base.respuesta = re.sub(r"\s*\[\d+\]", "", texto).strip()  # Las marcas [n] sirven para citar, no para el usuario.
    base.fuentes = _fuentes(fragmentos, usados)
    base.sin_contexto = False
    return base
