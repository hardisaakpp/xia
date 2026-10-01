"""Identidad y permisos: quién pregunta y qué documentación puede ver.

La identidad sale del JWT de SCNexus Core (HS256, claims `name`, `role` y `permission`), no del cuerpo de la petición.
Cada documento indexado declara los permisos que lo habilitan (`documentos.permisos`); la búsqueda solo ve los documentos
permitidos, así que el modelo nunca recibe fragmentos que el usuario no puede leer.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import jwt

from xia import db
from xia.config import get_settings
from xia.errores import XiaError

_CLAIM_NOMBRE = ("http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name", "unique_name", "name", "sub")
_CLAIM_ROL = ("http://schemas.microsoft.com/ws/2008/06/identity/claims/role", "role", "roles")
_CACHE_TTL_S = 30.0


@dataclass(frozen=True)
class Identidad:
    usuario: str
    permisos: frozenset[str] = field(default_factory=frozenset)
    roles: frozenset[str] = field(default_factory=frozenset)
    todo: bool = False  # acceso total sin consultar permisos (administrador o modo desarrollo)

    @property
    def es_admin(self) -> bool:
        return self.todo or any(r.lower() in {x.lower() for x in get_settings().roles_admin} for r in self.roles)


def _como_lista(valor: object) -> list[str]:
    if valor is None:
        return []
    return [str(v) for v in valor] if isinstance(valor, (list, tuple)) else [str(valor)]


def _primero(claims: dict, nombres: tuple[str, ...]) -> list[str]:
    for n in nombres:
        if n in claims:
            return _como_lista(claims[n])
    return []


def identidad_desde_claims(claims: dict) -> Identidad:
    nombre = next(iter(_primero(claims, _CLAIM_NOMBRE)), "")
    if not nombre:
        raise XiaError("no-autenticado", "El token no identifica a ningún usuario.", 401)
    return Identidad(
        usuario=nombre.strip(),
        permisos=frozenset(p.strip().lower() for p in _como_lista(claims.get("permission"))),
        roles=frozenset(_primero(claims, _CLAIM_ROL)),
    )


def validar_configuracion() -> None:
    """Falla al arrancar si se exige JWT y falta la clave: mejor no levantar que quedar abierto o rechazar a todos."""
    s = get_settings()
    if s.autenticacion == "jwt" and not s.jwt_secret:
        raise RuntimeError("XIA_AUTENTICACION=jwt requiere XIA_JWT_SECRET (misma clave que SCNexus Core). "
                           "Para desarrollo sin Core: XIA_AUTENTICACION=ninguna.")
    if s.autenticacion not in ("jwt", "ninguna"):
        raise RuntimeError(f"XIA_AUTENTICACION desconocida: {s.autenticacion!r} (use 'jwt' o 'ninguna')")


def identificar(authorization: str | None, usuario_ad: str | None) -> Identidad:
    """Identidad de la petición. `usuario_ad` solo se respeta en modo desarrollo (`autenticacion=ninguna`)."""
    s = get_settings()
    if s.autenticacion == "ninguna":
        usuario = (usuario_ad or "").strip()
        if not usuario:
            raise XiaError("peticion-invalida", "La petición no es válida.", 400)
        return Identidad(usuario=usuario, todo=True)

    if not authorization or not authorization.lower().startswith("bearer "):
        raise XiaError("no-autenticado", "Inicia sesión para usar el asistente.", 401)
    token = authorization[7:].strip()
    opciones = {"require": ["exp"], "verify_aud": bool(s.jwt_audience), "verify_iss": bool(s.jwt_issuer)}
    try:
        claims = jwt.decode(token, s.jwt_secret, algorithms=["HS256"], options=opciones,
                            audience=s.jwt_audience or None, issuer=s.jwt_issuer or None, leeway=120)
    except jwt.ExpiredSignatureError:
        raise XiaError("no-autenticado", "Tu sesión venció. Vuelve a iniciar sesión.", 401) from None
    except jwt.InvalidTokenError:
        raise XiaError("no-autenticado", "Tu sesión no es válida. Vuelve a iniciar sesión.", 401) from None
    return identidad_desde_claims(claims)


def cumple(requeridos: list[str] | tuple[str, ...], permisos: frozenset[str]) -> bool:
    """¿Alguno de los permisos requeridos está en los del usuario? `modulo.*` es un prefijo y `*` admite a cualquiera."""
    for r in (x.strip().lower() for x in requeridos):
        if r == "*" or r in permisos:
            return True
        if r.endswith(".*") and any(p.startswith(r[:-1]) for p in permisos):
            return True
    return False


_cache: tuple[float, list[tuple[int, str, list[str]]]] | None = None


def _documentos() -> list[tuple[int, str, list[str]]]:
    global _cache
    ahora = time.monotonic()
    if _cache is None or ahora - _cache[0] > _CACHE_TTL_S:
        with db.pool().connection() as conn:
            filas = conn.execute("SELECT id, area, permisos FROM documentos").fetchall()
        _cache = (ahora, [(i, a, list(p or [])) for i, a, p in filas])
    return _cache[1]


def invalidar_cache() -> None:
    global _cache
    _cache = None


@dataclass(frozen=True)
class Alcance:
    """Qué puede ver un usuario. `documentos=None` = todo."""
    areas: frozenset[str]
    documentos: list[int] | None


def alcance(identidad: Identidad) -> Alcance:
    docs = _documentos()
    if identidad.es_admin:
        return Alcance(frozenset(a for _, a, _ in docs), None)
    permitidos = [(i, a) for i, a, req in docs if cumple(req, identidad.permisos)]
    return Alcance(frozenset(a for _, a in permitidos), [i for i, _ in permitidos])
