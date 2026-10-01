import numpy as np
import pytest

from xia import intencion
from xia.config import get_settings


@pytest.fixture(autouse=True)
def ejemplos_falsos(monkeypatch):
    """Una sola frase de ejemplo (vector unitario en el eje 0), sin llamar a Ollama."""
    monkeypatch.setattr(intencion, "_vectores", np.array([[1.0, 0.0]], dtype=np.float32))


def test_mensaje_largo_nunca_es_charla():
    # Aunque el vector sea idéntico al ejemplo, más de MAX_PALABRAS_CHARLA palabras va a la documentación.
    largo = "hola " + "palabra " * intencion.MAX_PALABRAS_CHARLA
    assert intencion.es_charla(largo, [1.0, 0.0], "m") is False


def test_muy_parecido_es_charla_sin_llamar_al_modelo(monkeypatch):
    monkeypatch.setattr(intencion, "_clasificar_con_llm", lambda *a: pytest.fail("no debía llamar al modelo"))
    assert intencion.es_charla("hola", [1.0, 0.0], "m") is True


def test_nada_parecido_es_consulta_sin_llamar_al_modelo(monkeypatch):
    monkeypatch.setattr(intencion, "_clasificar_con_llm", lambda *a: pytest.fail("no debía llamar al modelo"))
    assert intencion.es_charla("pedidos", [0.0, 1.0], "m") is False


def test_zona_dudosa_decide_el_modelo(monkeypatch):
    s = get_settings()
    medio = (s.umbral_charla_dudoso + s.umbral_charla_seguro) / 2
    vector = [medio, float(np.sqrt(1 - medio**2))]  # similitud coseno = medio
    monkeypatch.setattr(intencion, "_clasificar_con_llm", lambda *a: True)
    assert intencion.es_charla("súper", vector, "m") is True
    monkeypatch.setattr(intencion, "_clasificar_con_llm", lambda *a: False)
    assert intencion.es_charla("ayuda con SAP", vector, "m") is False
