"""Detección de charla (saludos, gracias, "¿quién eres?", "¿qué puedes hacer?") antes de buscar en la documentación.

Tres zonas según la similitud del embedding (ya calculado para buscar) con unas frases de ejemplo:
  - muy parecido a la charla  -> charla, sin gastar el modelo;
  - nada parecido             -> consulta;
  - en medio                  -> el modelo decide con una llamada de una palabra.
La similitud sola no basta: "ayuda con SAP" (consulta real) se parece más a "ayuda" que "súper" a cualquier saludo.
Un mensaje largo nunca es charla: "hola, ¿qué estado tiene un pedido?" debe ir a la documentación.
"""
from __future__ import annotations

import re
import threading

import numpy as np

from xia.config import get_settings
from xia.llm import embeber, generar

# Mensajes con más palabras que esto no se consideran charla, sin importar su similitud.
MAX_PALABRAS_CHARLA = 8

EJEMPLOS_CHARLA = [
    # saludos
    "hola", "buenas", "buenos días", "buenas tardes", "buenas noches", "hola, ¿cómo estás?", "¿qué tal?", "saludos",
    "hola xia", "hey",
    # agradecimientos y cierres
    "gracias", "muchas gracias", "te agradezco", "gracias por tu ayuda", "listo, gracias", "perfecto, gracias",
    "adiós", "hasta luego", "chao", "nos vemos", "que tengas un buen día",
    # identidad y capacidades
    "¿quién eres?", "¿cómo te llamas?", "¿qué eres?", "¿eres un robot?", "¿qué puedes hacer?",
    "¿en qué me puedes ayudar?", "¿para qué sirves?", "ayuda", "¿cómo funcionas?", "¿qué temas conoces?",
    # asentimientos
    "ok", "entendido", "vale", "genial", "perfecto",
]

_PALABRA = re.compile(r"\w+", re.UNICODE)
_lock = threading.Lock()
_vectores: np.ndarray | None = None


def _normalizar(m: np.ndarray) -> np.ndarray:
    return m / np.linalg.norm(m, axis=-1, keepdims=True)


def _matriz_ejemplos() -> np.ndarray:
    global _vectores
    if _vectores is None:
        with _lock:
            if _vectores is None:
                _vectores = _normalizar(np.array(embeber(EJEMPLOS_CHARLA), dtype=np.float32))
    return _vectores


def precalentar() -> None:
    """Calcula los embeddings de ejemplo (una sola vez) para que la primera consulta no pague ese costo."""
    _matriz_ejemplos()


def similitud_charla(vector: list[float]) -> float:
    """Mayor similitud coseno entre el mensaje y las frases de ejemplo de charla."""
    v = _normalizar(np.array(vector, dtype=np.float32))
    return float(np.max(_matriz_ejemplos() @ v))


_SISTEMA_CLASIFICAR = """Clasificas mensajes dirigidos a un asistente que responde preguntas sobre la documentación de procesos de una empresa (pedidos, órdenes de compra, SAP, permisos).

Responde con UNA sola palabra:
- CHARLA: saludos, despedidas, agradecimientos, asentimientos, o preguntas sobre el propio asistente (quién es, qué puede hacer, cómo usarlo).
- CONSULTA: cualquier otro mensaje: pedidos de información o ayuda sobre un tema, proceso, error, estado, permiso o sistema (aunque sea de una sola palabra) e incluso temas ajenos a la empresa; de esos últimos se encarga otro paso.

Ejemplos:
"buenas noches" -> CHARLA
"¿puedes explicarme qué haces?" -> CHARLA
"listo, entendido" -> CHARLA
"inventario" -> CONSULTA
"error al guardar" -> CONSULTA
"ayuda con facturas" -> CONSULTA
"¿quién aprueba los pagos?" -> CONSULTA
"¿quién ganó el mundial?" -> CONSULTA"""


def _clasificar_con_llm(pregunta: str, modelo: str) -> bool:
    salida = generar([{"role": "system", "content": _SISTEMA_CLASIFICAR}, {"role": "user", "content": f'"{pregunta}" ->'}],
                     modelo, temperatura=0.0)
    return salida.strip().upper().startswith("CHARLA")


def es_charla(pregunta: str, vector: list[float], modelo: str | None = None) -> bool:
    s = get_settings()
    if len(_PALABRA.findall(pregunta)) > MAX_PALABRAS_CHARLA:
        return False
    sim = similitud_charla(vector)
    if sim >= s.umbral_charla_seguro:
        return True
    if sim < s.umbral_charla_dudoso:
        return False
    return _clasificar_con_llm(pregunta, modelo or s.modelo_generacion)
