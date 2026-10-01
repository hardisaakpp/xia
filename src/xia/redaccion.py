"""Redacción de secretos antes de indexar.

Xia responde a cualquier usuario del chat y aún no filtra por permisos de área: lo que se indexa se puede preguntar.
Los documentos técnicos suelen traer credenciales de ejemplo (`password = "Admin123!"`), así que se enmascaran aquí,
antes de trocear y de calcular los embeddings. Se enmascara el VALOR, no la clave: "el usuario es admin y la
contraseña va en `password`" sigue siendo documentación válida.
"""
from __future__ import annotations

import re

MARCA = "<redactado>"

_CLAVE = r"(?:password|passwd|pwd|contraseña|contrasena|clave|secret|secreto|api[_-]?key|client[_-]?secret|jwt[_-]?secret)"

# clave = "valor" | clave: 'valor' | "clave": "valor"  (valor entre comillas)
_CON_COMILLAS = re.compile(
    rf"(?i)(?P<pre>[\"']?\b\w*{_CLAVE}\w*[\"']?\s*[:=]\s*)(?P<q>[\"'])(?P<v>[^\"'\n]+)(?P=q)")
# Clave=valor sin comillas (variables de entorno, cadenas de conexión): termina en espacio, ; o fin de línea
_SIN_COMILLAS = re.compile(
    rf"(?i)(?P<pre>\b[\w.]*{_CLAVE}[\w.]*\s*=\s*)(?P<v>[^\s;\"'`]+)")
# Markdown: **Password:** `valor`  |  Password: `valor`  |  | Password | `valor` |
_CLAVE_MD = r"(?:password|passwd|pwd|contraseña|contrasena|secret|secreto|api[_-]?key|client[_-]?secret)"
_MARKDOWN = re.compile(rf"(?i)(?P<pre>\b{_CLAVE_MD}\b[\s*]*[:|][\s:*|]*)`(?P<v>[^`\n]+)`")
# Tokens JWT completos (tres segmentos base64url que empiezan por eyJ)
_JWT = re.compile(r"\beyJ[\w-]{10,}\.[\w-]{10,}\.[\w-]{5,}")


def redactar(texto: str) -> str:
    texto = _CON_COMILLAS.sub(lambda m: f"{m['pre']}{m['q']}{MARCA}{m['q']}", texto)
    texto = _SIN_COMILLAS.sub(lambda m: f"{m['pre']}{MARCA}", texto)
    texto = _MARKDOWN.sub(lambda m: f"{m['pre']}`{MARCA}`", texto)
    return _JWT.sub(MARCA, texto)
