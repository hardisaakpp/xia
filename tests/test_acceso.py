import time

import jwt
import pytest

from xia import acceso
from xia.config import get_settings
from xia.errores import XiaError

SECRETO = "clave-de-prueba-con-longitud-suficiente-para-hs256"
CLAIM_NOMBRE = "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name"
CLAIM_ROL = "http://schemas.microsoft.com/ws/2008/06/identity/claims/role"


@pytest.fixture(autouse=True)
def config_jwt(monkeypatch):
    s = get_settings()
    for campo, valor in {"autenticacion": "jwt", "jwt_secret": SECRETO, "jwt_issuer": "SCNexus.Core",
                         "jwt_audience": "SCNexus.Users"}.items():
        monkeypatch.setattr(s, campo, valor)


def token(**extra):
    claims = {CLAIM_NOMBRE: "mperez", "permission": ["odcsap.view", "Inventario.Toma"], "iss": "SCNexus.Core",
              "aud": "SCNexus.Users", "exp": int(time.time()) + 3600, **extra}
    return jwt.encode(claims, SECRETO, algorithm="HS256")


def test_token_valido_da_usuario_permisos_y_roles():
    i = acceso.identificar(f"Bearer {token(**{CLAIM_ROL: ['Tienda']})}", "otro-usuario")
    assert i.usuario == "mperez"  # el usuario sale del token, NO del cuerpo
    assert i.permisos == {"odcsap.view", "inventario.toma"}  # normalizados a minúsculas
    assert i.roles == {"Tienda"} and not i.es_admin


def test_un_solo_permiso_llega_como_texto_no_como_lista():
    i = acceso.identificar(f"Bearer {token(permission='odcsap.view')}", None)
    assert i.permisos == {"odcsap.view"}


def test_rol_admin_en_lista_o_texto():
    assert acceso.identificar(f"Bearer {token(**{CLAIM_ROL: 'Admin'})}", None).es_admin
    assert acceso.identificar(f"Bearer {token(**{CLAIM_ROL: ['Tienda', 'admin']})}", None).es_admin


@pytest.mark.parametrize("cabecera", [None, "", "Basic abc", "Bearer", "Bearer basura"])
def test_sin_token_o_malformado_es_401(cabecera):
    with pytest.raises(XiaError) as e:
        acceso.identificar(cabecera, "mperez")
    assert e.value.status == 401 and e.value.codigo == "no-autenticado"


def test_firma_incorrecta_vencido_emisor_o_audiencia_distintos():
    malos = [
        jwt.encode({CLAIM_NOMBRE: "x", "iss": "SCNexus.Core", "aud": "SCNexus.Users", "exp": int(time.time()) + 60},
                   "otra-clave-distinta-de-longitud-suficiente-0123", algorithm="HS256"),
        token(exp=int(time.time()) - 3600),
        token(iss="Otro"),
        token(aud="Otra"),
    ]
    for t in malos:
        with pytest.raises(XiaError) as e:
            acceso.identificar(f"Bearer {t}", None)
        assert e.value.status == 401


def test_token_sin_expiracion_o_sin_algoritmo_hs256_se_rechaza():
    sin_exp = jwt.encode({CLAIM_NOMBRE: "x", "iss": "SCNexus.Core", "aud": "SCNexus.Users"}, SECRETO, algorithm="HS256")
    sin_firma = jwt.encode({CLAIM_NOMBRE: "x", "iss": "SCNexus.Core", "aud": "SCNexus.Users", "exp": int(time.time()) + 60},
                           None, algorithm="none")
    for t in (sin_exp, sin_firma):
        with pytest.raises(XiaError):
            acceso.identificar(f"Bearer {t}", None)


def test_modo_desarrollo_confia_en_usuario_ad_y_da_acceso_total(monkeypatch):
    monkeypatch.setattr(get_settings(), "autenticacion", "ninguna")
    i = acceso.identificar(None, "dev")
    assert i.usuario == "dev" and i.es_admin
    with pytest.raises(XiaError):
        acceso.identificar(None, "  ")


def test_arranque_falla_si_se_exige_jwt_sin_clave(monkeypatch):
    monkeypatch.setattr(get_settings(), "jwt_secret", "")
    with pytest.raises(RuntimeError):
        acceso.validar_configuracion()


@pytest.mark.parametrize("requeridos, permisos, esperado", [
    (["odcsap.view"], {"odcsap.view"}, True),
    (["odcsap.view"], {"mabel.view"}, False),
    (["a.view", "b.view"], {"b.view"}, True),            # basta uno
    (["inventario.*"], {"inventario.toma"}, True),         # prefijo
    (["inventario.*"], {"inventariox.toma"}, False),       # el prefijo exige el punto
    (["inventario.*"], {"inventario"}, False),
    (["*"], set(), True),                                  # cualquier usuario autenticado
    ([], {"odcsap.view"}, False),                          # sin permisos declarados: nadie (solo admin)
    (["xia.tecnico"], {"xia.tecnico"}, True),
    (["Promocion.Sobres.*"], {"promocion.sobres.operate"}, True),
])
def test_cumple(requeridos, permisos, esperado):
    assert acceso.cumple(requeridos, frozenset(permisos)) is esperado
