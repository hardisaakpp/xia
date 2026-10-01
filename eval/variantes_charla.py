"""Regresión de la detección de charla con variantes: otros idiomas, informales, mayúsculas y errores de tipeo.

    python eval/variantes_charla.py

Resultado 2026-10-01: 45/46 (falla "ayúdame", ambigua a propósito). Es una medición, no un test de CI: usa Ollama.
"""
from xia import db
from xia.intencion import es_charla, similitud_charla
from xia.llm import embeber
V = {
 "saludo": ["hi", "hello", "hey there", "holaaa", "holi", "wenas", "ola", "good morning", "HOLA", "hoal", "Hola!!", "buenas!", "buen dia",
            "q tal", "qué más", "saludos cordiales", "hola, buenas tardes", "ey", "alo", "hi xia"],
 "gracias": ["thanks", "thank you", "thx", "grax", "gracias!!", "gracias totales", "gracas", "mil gracias!", "ok, gracias", "muy amable"],
 "despedida": ["bye", "chau", "ciao", "hasta mañana", "nos vemos luego", "cuídate", "goodbye", "hasta la próxima"],
 "identidad": ["who are you", "what can you do", "como te llamas", "eres humano", "¿qué haces?", "para qué sirves tú", "help", "ayúdame"],
}
db.pool()
fallos = 0; llm = 0
from xia.config import get_settings
s = get_settings()
for cat, frases in V.items():
    vecs = embeber(frases)
    for f, v in zip(frases, vecs):
        sim = similitud_charla(v)
        zona = "seguro" if sim >= s.umbral_charla_seguro else "consulta" if sim < s.umbral_charla_dudoso else "dudoso"
        llm += zona == "dudoso"
        ok = es_charla(f, v)
        if not ok:
            fallos += 1; print(f"  ✗ [{cat}] {f!r}  sim={sim:.3f} zona={zona}")
total = sum(len(x) for x in V.values())
print(f"\nDetectadas: {total-fallos}/{total}   (pasaron por el modelo: {llm})")
db.cerrar_pool()
