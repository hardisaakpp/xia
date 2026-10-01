"""Lista las preguntas reales hechas a Xia (tabla `consultas`) para elegir cuáles sumar a eval/preguntas.yaml.

    python eval/revisar_consultas.py                 # distintas, de las más repetidas a las menos
    python eval/revisar_consultas.py --solo-sin-respuesta
    python eval/revisar_consultas.py --excluir prueba.dev

Una pregunta sin respuesta es una de dos: la documentación no cubre el tema (hay que documentarlo) o la
recuperación/el modelo falló (hay que arreglar Xia). Para decidir cuál, abrir el documento esperado y buscar.
"""
from __future__ import annotations

import argparse

from xia import db


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--solo-sin-respuesta", action="store_true")
    ap.add_argument("--excluir", action="append", default=[], help="usuario_ad a ignorar (repetible), p. ej. cuentas de prueba")
    args = ap.parse_args()

    filtros = ["error IS NULL", "NOT (usuario_ad = ANY(%(excluir)s))"]
    if args.solo_sin_respuesta:
        filtros.append("sin_contexto")
    sql = f"""
        SELECT pregunta, count(*) AS veces, count(*) FILTER (WHERE sin_contexto) AS sin_resp,
               count(DISTINCT usuario_ad) AS usuarios, max(creada) AS ultima
        FROM consultas WHERE {' AND '.join(filtros)}
        GROUP BY pregunta ORDER BY veces DESC, ultima DESC
    """
    with db.pool().connection() as conn:
        filas = conn.execute(sql, {"excluir": args.excluir}).fetchall()
    db.cerrar_pool()

    if not filas:
        print("No hay consultas que mostrar con esos filtros.")
        return
    for pregunta, veces, sin_resp, usuarios, ultima in filas:
        marca = "✗ sin respuesta" if sin_resp == veces else ("~ a veces sin respuesta" if sin_resp else "✓")
        print(f"{marca:24} x{veces} ({usuarios} usuario/s)  {pregunta}")
    print(f"\n{len(filas)} preguntas distintas. Para sumarlas al set: agregar a eval/preguntas.yaml con `contiene` y `documentos`.")


if __name__ == "__main__":
    main()
