from xia.retrieval import tokens_exactos


def test_detecta_numeros_e_identificadores():
    assert tokens_exactos("¿Qué hace la migración 665?") == ["665"]
    assert tokens_exactos("¿Qué es estado_id y la ODC 24712?") == ["24712", "estado_id"]


def test_sin_identificadores_no_hay_tokens_exactos():
    assert tokens_exactos("¿Qué estado tiene un pedido cuando falla el envío?") == []


def test_es_insensible_a_mayusculas_y_no_repite():
    assert tokens_exactos("Migración 665 y migración 665 y PED_1") == ["665", "ped_1"]
