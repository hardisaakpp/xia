"""Indexador incremental: lee las fuentes de sources.yaml y deja la BD sincronizada.

    python -m xia.indexer              # todas las áreas, solo lo que cambió
    python -m xia.indexer --area odc-mba3 --forzar
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import logging
from pathlib import Path
from typing import Any

import yaml
from pgvector import Vector

from xia import acceso, db
from xia.chunking import trocear
from xia.config import get_settings
from xia.llm import embeber
from xia.redaccion import redactar

log = logging.getLogger("xia.indexer")
logging.getLogger("httpx").setLevel(logging.WARNING)


def _cargar_fuentes() -> tuple[list[dict[str, Any]], Path]:
    archivo = Path(get_settings().sources_file).resolve()
    return yaml.safe_load(archivo.read_text(encoding="utf-8"))["areas"], archivo.parent


def _titulo(markdown: str, ruta: Path) -> str:
    for linea in markdown.splitlines():
        if linea.startswith("# "):
            return linea[2:].strip()
    return ruta.stem.replace("_", " ")


def _archivos(area: dict[str, Any], base: Path) -> dict[str, Path]:
    fuente = area["fuente"]
    if fuente["tipo"] != "carpeta":
        raise ValueError(f"Tipo de fuente no soportado: {fuente['tipo']}")
    raiz = (base / fuente["ruta"]).resolve()
    excluidos = {p for patron in fuente.get("excluir", []) for p in raiz.glob(patron)}
    encontrados: dict[str, Path] = {}
    for patron in fuente.get("patrones", ["**/*.md"]):
        for p in sorted(raiz.glob(patron)):
            if p.is_file() and p not in excluidos:
                encontrados[p.relative_to(raiz).as_posix()] = p
    return encontrados


def _permisos_de(area: dict[str, Any], ruta: str) -> list[str]:
    """Permisos que habilitan un documento: la primera regla de `permisos_por_patron` que coincida con su ruta o, si
    no hay, los del área. Sin ninguno declarado queda [] = solo administradores (denegar por defecto)."""
    for regla in area.get("permisos_por_patron", []):
        if fnmatch.fnmatch(ruta, regla["patron"]):
            return list(regla["permisos"])
    return list(area.get("permisos", []))


def indexar_area(area: dict[str, Any], base: Path, forzar: bool = False) -> dict[str, int]:
    codigo = area["codigo"]
    resumen = {"nuevos": 0, "actualizados": 0, "sin_cambios": 0, "eliminados": 0, "fragmentos": 0}
    archivos = _archivos(area, base)

    with db.pool().connection() as conn:
        conn.execute(
            "INSERT INTO areas (codigo, nombre, descripcion, ejemplos) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (codigo) DO UPDATE SET nombre = EXCLUDED.nombre, descripcion = EXCLUDED.descripcion, "
            "ejemplos = EXCLUDED.ejemplos",
            (codigo, area["nombre"], area.get("descripcion"), area.get("ejemplos") or []),
        )
        existentes = {r[0]: (r[1], r[2]) for r in conn.execute(
            "SELECT ruta, id, hash FROM documentos WHERE area = %s", (codigo,))}
        if not area.get("permisos") and not area.get("permisos_por_patron"):
            log.warning("[%s] sin `permisos`: sus documentos solo los verán administradores", codigo)

        for ruta, path in archivos.items():
            # Se redacta ANTES de calcular la huella: si cambian las reglas de redacción, el documento se reindexa.
            contenido = redactar(path.read_text(encoding="utf-8", errors="replace"))
            huella = hashlib.sha256(contenido.encode()).hexdigest()
            previo = existentes.get(ruta)
            permisos = _permisos_de(area, ruta)
            if previo and previo[1] == huella and not forzar:
                # El contenido no cambió, pero los permisos sí pueden haber cambiado en sources.yaml.
                conn.execute("UPDATE documentos SET permisos = %s WHERE id = %s", (permisos, previo[0]))
                resumen["sin_cambios"] += 1
                continue

            titulo = _titulo(contenido, path)
            fragmentos = trocear(contenido, titulo, get_settings().max_chars_fragmento)
            if not fragmentos:
                continue
            vectores = embeber([f"{f.encabezados}\n\n{f.texto}" for f in fragmentos])

            with conn.transaction():
                if previo:
                    conn.execute("DELETE FROM documentos WHERE id = %s", (previo[0],))
                    resumen["actualizados"] += 1
                else:
                    resumen["nuevos"] += 1
                doc_id = conn.execute(
                    "INSERT INTO documentos (area, ruta, titulo, hash, permisos) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                    (codigo, ruta, titulo, huella, permisos),
                ).fetchone()[0]
                with conn.cursor() as cur:
                    cur.executemany(
                        "INSERT INTO fragmentos (documento_id, area, orden, encabezados, texto, embedding) "
                        "VALUES (%s, %s, %s, %s, %s, %s)",
                        [(doc_id, codigo, f.orden, f.encabezados, f.texto, Vector(v)) for f, v in zip(fragmentos, vectores)],
                    )
            resumen["fragmentos"] += len(fragmentos)
            log.info("[%s] %s: %d fragmentos", codigo, ruta, len(fragmentos))

        for ruta, (doc_id, _) in existentes.items():
            if ruta not in archivos:
                conn.execute("DELETE FROM documentos WHERE id = %s", (doc_id,))
                resumen["eliminados"] += 1
    return resumen


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description="Indexa las fuentes de sources.yaml")
    ap.add_argument("--area", help="Código de un área (por defecto, todas)")
    ap.add_argument("--forzar", action="store_true", help="Reindexar aunque el archivo no haya cambiado")
    args = ap.parse_args()

    db.iniciar_esquema()
    areas, base = _cargar_fuentes()
    for area in areas:
        if args.area and area["codigo"] != args.area:
            continue
        print(f"{area['codigo']}: {indexar_area(area, base, args.forzar)}")
    db.cerrar_pool()


if __name__ == "__main__":
    main()
