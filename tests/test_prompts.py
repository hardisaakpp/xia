"""Los prompts del sistema se personalizan por despliegue (organización) y por petición (idioma)."""
from xia.pipeline import _IDIOMAS, _SISTEMA, _SISTEMA_CHARLA


def test_prompt_de_consulta_usa_organizacion_e_idioma():
    texto = _SISTEMA.format(organizacion="Stockline", idioma=_IDIOMAS["en"])
    assert "asistente de Stockline" in texto
    assert "Responde en English" in texto
    assert "{" not in texto


def test_prompt_de_charla_usa_organizacion_e_idioma():
    texto = _SISTEMA_CHARLA.format(temas="Pedidos", ejemplo="", organizacion="Stockline", idioma=_IDIOMAS["es"])
    assert "asistente virtual de Stockline" in texto
    assert "Responde en español" in texto
    assert "SCNEXUS" not in texto
