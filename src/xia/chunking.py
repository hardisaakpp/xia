"""Troceado de Markdown por encabezados.

Cada fragmento conserva su ruta de encabezados ("Título > Sección > Subsección"), que se indexa junto al
texto: una frase suelta como "se reintenta desde el panel" no dice nada sin saber de qué sección viene.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_ENCABEZADO = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_CERCA = re.compile(r"^\s*(```|~~~)")
# Secciones más cortas que esto se pegan a la siguiente en vez de quedar como fragmentos casi vacíos.
MIN_SECCION = 200


@dataclass(frozen=True)
class Fragmento:
    orden: int
    encabezados: str
    texto: str


def trocear(markdown: str, titulo: str, max_chars: int = 1500) -> list[Fragmento]:
    fragmentos: list[Fragmento] = []
    pendiente = ""
    ultima_ruta: list[str] = [titulo]

    for ruta, cuerpo in _secciones(markdown, titulo):
        cuerpo = cuerpo.strip()
        if not cuerpo:
            continue
        ultima_ruta = ruta
        if len(cuerpo) < MIN_SECCION:
            pendiente += f"{ruta[-1]}\n{cuerpo}\n\n"
            continue
        texto, pendiente = pendiente + cuerpo, ""
        for trozo in _empaquetar(_bloques(texto), max_chars):
            fragmentos.append(Fragmento(len(fragmentos), " > ".join(ruta), trozo))

    if pendiente.strip():
        for trozo in _empaquetar(_bloques(pendiente), max_chars):
            fragmentos.append(Fragmento(len(fragmentos), " > ".join(ultima_ruta), trozo))
    return fragmentos


def _secciones(markdown: str, titulo: str) -> list[tuple[list[str], str]]:
    """Divide en (ruta de encabezados, cuerpo). Ignora '#' dentro de bloques de código."""
    secciones: list[tuple[list[str], str]] = []
    pila: list[tuple[int, str]] = []
    lineas: list[str] = []
    en_codigo = False

    def ruta_actual() -> list[str]:
        ruta = [texto for _, texto in pila]
        return ruta if ruta and ruta[0] == titulo else [titulo, *ruta]

    for linea in markdown.splitlines():
        if _CERCA.match(linea):
            en_codigo = not en_codigo
        m = None if en_codigo else _ENCABEZADO.match(linea)
        if m:
            secciones.append((ruta_actual(), "\n".join(lineas)))
            lineas = []
            nivel = len(m.group(1))
            while pila and pila[-1][0] >= nivel:
                pila.pop()
            pila.append((nivel, m.group(2)))
        else:
            lineas.append(linea)
    secciones.append((ruta_actual(), "\n".join(lineas)))
    return secciones


def _bloques(texto: str) -> list[str]:
    """Párrafos separados por línea en blanco; un bloque de código cercado nunca se parte."""
    bloques: list[str] = []
    actual: list[str] = []
    en_codigo = False
    for linea in texto.splitlines():
        if _CERCA.match(linea):
            en_codigo = not en_codigo
        if not linea.strip() and not en_codigo:
            if actual:
                bloques.append("\n".join(actual))
                actual = []
        else:
            actual.append(linea)
    if actual:
        bloques.append("\n".join(actual))
    return bloques


def _empaquetar(bloques: list[str], max_chars: int) -> list[str]:
    trozos: list[str] = []
    actual = ""
    for bloque in bloques:
        for parte in _partir(bloque, max_chars):
            if actual and len(actual) + len(parte) + 2 > max_chars:
                trozos.append(actual)
                actual = parte
            else:
                actual = f"{actual}\n\n{parte}" if actual else parte
    if actual:
        trozos.append(actual)
    return trozos


def _partir(bloque: str, max_chars: int) -> list[str]:
    """Un bloque más grande que el máximo (tabla o código largo) se parte por líneas, y por caracteres como último recurso."""
    if len(bloque) <= max_chars:
        return [bloque]
    partes: list[str] = []
    actual = ""
    for linea in bloque.splitlines():
        while len(linea) > max_chars:
            if actual:
                partes.append(actual)
                actual = ""
            partes.append(linea[:max_chars])
            linea = linea[max_chars:]
        if actual and len(actual) + len(linea) + 1 > max_chars:
            partes.append(actual)
            actual = linea
        else:
            actual = f"{actual}\n{linea}" if actual else linea
    if actual:
        partes.append(actual)
    return partes
