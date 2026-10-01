"""Mide solo la recuperación (sin generar respuestas): rápido y determinista.

    python eval/run_retrieval.py                       # banco difícil, sin reranker
    python eval/run_retrieval.py --top-k 3 -v          # más exigente: ver cada pregunta

Métricas: hit@k (¿algún documento esperado entre los k primeros fragmentos?) y MRR (1/posición del primero).
"""
from __future__ import annotations

import argparse
import statistics
import time
from pathlib import Path

import yaml

from xia import db
from xia.config import get_settings
from xia.llm import embeber
from xia.pipeline import buscar

AQUI = Path(__file__).parent


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--banco", default="recuperacion_dificil.yaml")
    ap.add_argument("--top-k", type=int, help="Sobrescribe XIA_TOP_K")
    ap.add_argument("--reranker", help="Sobrescribe XIA_RERANKER (ninguno | cross-encoder)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    s = get_settings()
    if args.top_k:
        s.top_k = args.top_k
    if args.reranker:
        s.reranker = args.reranker
    preguntas = yaml.safe_load((AQUI / args.banco).read_text(encoding="utf-8"))

    db.pool()
    areas = ["odc-mba3"]
    rangos, tiempos = [], []
    for p in preguntas:
        inicio = time.perf_counter()
        fragmentos = buscar(p["pregunta"], areas)
        tiempos.append(time.perf_counter() - inicio)
        docs = [f.ruta for f in fragmentos]
        rango = next((i + 1 for i, d in enumerate(docs) if d in p["documentos"]), None)
        rangos.append(rango)
        if args.verbose or rango is None:
            print(f"{'✓' if rango else '✗'} pos={rango or '-'}  {p['pregunta']}")
            if rango is None or args.verbose:
                print("     recuperó:", [d[:28] for d in dict.fromkeys(docs)])
    n = len(rangos)
    print(f"\nreranker={s.reranker} top_k={s.top_k} preguntas={n}")
    for k in (1, 3, s.top_k):
        print(f"  hit@{k}: {sum(1 for r in rangos if r and r <= k)}/{n}")
    print(f"  MRR: {statistics.mean(1 / r if r else 0 for r in rangos):.3f}")
    print(f"  latencia de búsqueda: mediana {statistics.median(tiempos) * 1000:.0f} ms")
    db.cerrar_pool()


if __name__ == "__main__":
    main()
