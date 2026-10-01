"""Evalúa el pipeline contra eval/preguntas.yaml. No usa la API ni gasta cuota: llama al pipeline directo.

    python eval/run_eval.py                              # modelo por defecto
    python eval/run_eval.py --modelos mistral:latest,qwen3:8b
    python eval/run_eval.py --umbral 0.5 --id estado-inicial

Mide por separado la recuperación (¿llegó el documento correcto?) y la generación (¿respondió bien?):
si la recuperación falla, cambiar de modelo no ayuda; si acierta y la respuesta falla, el culpable es el modelo.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
import unicodedata
from pathlib import Path

import yaml

from xia import db
from xia.config import get_settings
from xia.errores import XiaError
from xia.pipeline import ejecutar

AQUI = Path(__file__).parent


def _norm(texto: str) -> str:
    sin_tildes = "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")
    return sin_tildes.casefold().replace("_", " ")


def _contiene(respuesta: str, requisitos: list) -> bool:
    r = _norm(respuesta)
    return all(
        any(_norm(str(alt)) in r for alt in (req if isinstance(req, list) else [req]))
        for req in requisitos
    )


def evaluar(pregunta: dict, modelo: str, usar_historial: bool = True) -> dict:
    inicio = time.perf_counter()
    try:
        res = ejecutar(pregunta["pregunta"], None, modelo, pregunta.get("historial") if usar_historial else None)
    except XiaError as e:
        return {"id": pregunta["id"], "error": e.codigo, "ok": False, "segundos": time.perf_counter() - inicio}
    segundos = time.perf_counter() - inicio

    fila = {"id": pregunta["id"], "respuesta": res.respuesta, "sin_contexto": res.sin_contexto,
            "similitud": round(res.mejor_similitud, 3), "segundos": round(segundos, 1)}
    fila["intencion"] = res.intencion
    if "charla" in pregunta:
        # charla: true  -> debe responder natural, sin fuentes ni "no encontré"; charla: false -> NO debe tomarse por charla.
        if pregunta["charla"]:
            fila["ok"] = res.intencion == "charla" and not res.sin_contexto and not res.fuentes
        else:
            fila["ok"] = res.intencion != "charla"
        fila["tipo"] = "charla"
    elif pregunta.get("sin_contexto"):
        fila["ok"] = res.sin_contexto
        fila["tipo"] = "rechazo"
    else:
        esperados = pregunta.get("documentos", [])
        fila["recuperacion_ok"] = any(d in res.documentos_recuperados for d in esperados)
        fila["fuente_ok"] = any(f["documento"] in esperados for f in res.fuentes)
        fila["ok"] = (not res.sin_contexto) and _contiene(res.respuesta, pregunta.get("contiene", []))
        fila["tipo"] = "respuesta"
        if not fila["ok"]:
            # Distinción clave: negarse sin motivo es molesto; responder mal con seguridad es peligroso.
            fila["falla"] = "falso_rechazo" if res.sin_contexto else "respuesta_incorrecta"
    return fila


def resumen(modelo: str, filas: list[dict]) -> None:
    resp = [f for f in filas if f.get("tipo") == "respuesta"]
    rech = [f for f in filas if f.get("tipo") == "rechazo"]
    charla = [f for f in filas if f.get("tipo") == "charla"]
    tiempos = [f["segundos"] for f in filas if "segundos" in f]
    print(f"\n=== {modelo} ===")
    print(f"  Respuestas correctas : {sum(f['ok'] for f in resp)}/{len(resp)}")
    print(f"  Recuperación acierta : {sum(f.get('recuperacion_ok', False) for f in resp)}/{len(resp)}")
    print(f"  Fuente citada ok     : {sum(f.get('fuente_ok', False) for f in resp)}/{len(resp)}")
    print(f"  Rechazos correctos   : {sum(f['ok'] for f in rech)}/{len(rech)}")
    if charla:
        print(f"  Charla / controles   : {sum(f['ok'] for f in charla)}/{len(charla)}")
    print(f"  Fallos               : {sum(f.get('falla') == 'falso_rechazo' for f in resp)} falsos rechazos, "
          f"{sum(f.get('falla') == 'respuesta_incorrecta' for f in resp)} respuestas incorrectas "
          f"(+ {sum(not f['ok'] for f in rech)} no rechazó lo que debía)")
    print(f"  Latencia             : mediana {statistics.median(tiempos):.1f}s, máx {max(tiempos):.1f}s")
    for f in filas:
        if not f["ok"]:
            print(f"  ✗ {f['id']}: " + (f.get("error") or f"[ctx={'no' if f['sin_contexto'] else 'sí'}, sim={f['similitud']}] {f['respuesta'][:160]!r}"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--modelos", help="Lista separada por comas (por defecto, el configurado)")
    ap.add_argument("--umbral", type=float, help="Sobrescribe XIA_UMBRAL_RELEVANCIA para esta corrida")
    ap.add_argument("--id", help="Solo una pregunta")
    ap.add_argument("--sin-historial", action="store_true",
                    help="Ignora el campo `historial` de las preguntas (línea base: cómo sería sin memoria)")
    args = ap.parse_args()

    s = get_settings()
    if args.umbral is not None:
        s.umbral_relevancia = args.umbral
    preguntas = yaml.safe_load((AQUI / "preguntas.yaml").read_text(encoding="utf-8"))
    if args.id:
        preguntas = [p for p in preguntas if p["id"] == args.id]
    modelos = args.modelos.split(",") if args.modelos else [s.modelo_generacion]

    db.pool()
    todo: dict[str, list[dict]] = {}
    for modelo in modelos:
        # Primera llamada "de calentamiento": cargar el modelo en GPU no debe contarse como latencia.
        try:
            ejecutar("hola", None, modelo)
        except XiaError:
            pass
        todo[modelo] = [evaluar(p, modelo, not args.sin_historial) for p in preguntas]
        resumen(modelo, todo[modelo])

    salida = AQUI / "resultados"
    salida.mkdir(exist_ok=True)
    archivo = salida / f"{time.strftime('%Y%m%d-%H%M%S')}.json"
    archivo.write_text(json.dumps({"umbral": s.umbral_relevancia, "resultados": todo}, ensure_ascii=False, indent=2))
    print(f"\nDetalle completo: {archivo}")
    db.cerrar_pool()


if __name__ == "__main__":
    main()
