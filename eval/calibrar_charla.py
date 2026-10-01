"""Calibra XIA_UMBRAL_CHARLA: muestra cómo se separan la charla real y las consultas, usando frases que NO están en los
ejemplos de src/xia/intencion.py (si no, mediría memoria y no generalización).

    python eval/calibrar_charla.py
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from xia import db
from xia.config import get_settings
from xia.intencion import MAX_PALABRAS_CHARLA, es_charla, similitud_charla
from xia.llm import embeber

AQUI = Path(__file__).parent
_PALABRAS = re.compile(r"\w+", re.UNICODE)

CHARLA = [
    "buen día", "qué onda", "muchísimas gracias por todo", "ok gracias", "mil gracias", "hasta pronto", "¿tú quién eres?",
    "¿qué sabes hacer?", "¿me puedes ayudar?", "necesito ayuda", "hola buenas tardes", "buenas, ¿cómo va todo?",
    "cuéntame qué haces", "¿cómo puedo usarte?", "ya entendí", "de acuerdo", "súper", "bye", "hola xia, ¿me ayudas?",
    "gracias, eso era todo", "¿quién te hizo?", "¿eres una inteligencia artificial?", "¿con qué me puedes ayudar?",
]
# Consultas cortas que NO deben tratarse como charla (las más riesgosas: poco texto, mucha ambigüedad).
CONSULTAS_CORTAS = [
    "pedidos", "ODC", "permisos", "estados del pedido", "ayuda con SAP", "error al enviar a SAP", "¿qué es una ODC?",
    "¿cómo cargo una plantilla?", "¿qué es redistribución?", "reintentar envío", "¿cómo funciona la reconciliación?",
    "¿qué hace el perfil Producción?", "SKU homologado", "¿qué significa 202?", "cancelar pedido",
]


def main() -> None:
    cfg = get_settings()
    db.pool()
    todas = [p["pregunta"] for p in yaml.safe_load((AQUI / "preguntas.yaml").read_text(encoding="utf-8")) if not p.get("sin_contexto") and p.get("charla") is not True]
    todas += [p["pregunta"] for p in yaml.safe_load((AQUI / "recuperacion_dificil.yaml").read_text(encoding="utf-8"))]
    # Solo cuentan como riesgo las que pasan el filtro de longitud (las largas nunca llegan a compararse).
    cortas = [q for q in todas if len(_PALABRAS.findall(q)) <= MAX_PALABRAS_CHARLA] + CONSULTAS_CORTAS
    todo = CHARLA + cortas
    vectores = embeber(todo)
    zona = {"seguro": 0, "dudoso": 0, "consulta": 0}
    decision = []
    for v, t in zip(vectores, todo):
        sim = similitud_charla(v)
        zona["seguro" if sim >= cfg.umbral_charla_seguro else "consulta" if sim < cfg.umbral_charla_dudoso else "dudoso"] += 1
        decision.append((es_charla(t, v), sim, t))
    aciertos = decision[: len(CHARLA)]
    falsas = decision[len(CHARLA):]
    print(f"CHARLA bien detectada : {sum(d for d, _, _ in aciertos)}/{len(CHARLA)}")
    for d, sim, t in aciertos:
        if not d:
            print(f"   ✗ no detectada ({sim:.3f}): {t}")
    print(f"CONSULTAS mal tomadas por charla: {sum(d for d, _, _ in falsas)}/{len(cortas)}")
    for d, sim, t in falsas:
        if d:
            print(f"   ✗ tomada por charla ({sim:.3f}): {t}")
    print(f"\nZonas (umbrales {cfg.umbral_charla_dudoso}/{cfg.umbral_charla_seguro}): {zona}  -> solo 'dudoso' gasta una llamada al modelo")
    db.cerrar_pool()


if __name__ == "__main__":
    main()
