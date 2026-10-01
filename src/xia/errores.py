from __future__ import annotations

from typing import Any


class XiaError(Exception):
    """Error del contrato mIA: `codigo` es lo que decide el frontend (no el status HTTP)."""

    def __init__(
        self,
        codigo: str,
        mensaje: str,
        status: int,
        *,
        cuota: dict[str, Any] | None = None,
        reintentar_en_segundos: int | None = None,
        detalles: list[dict[str, str]] | None = None,
    ) -> None:
        super().__init__(mensaje)
        self.codigo = codigo
        self.mensaje = mensaje
        self.status = status
        self.cuota = cuota
        self.reintentar_en_segundos = reintentar_en_segundos
        self.detalles = detalles
        self.traza_id: str | None = None

    def cuerpo(self) -> dict[str, Any]:
        cuerpo: dict[str, Any] = {"error": self.codigo, "message": self.mensaje}
        if self.traza_id:
            cuerpo["traza_id"] = self.traza_id
        if self.cuota:
            cuerpo["cuota"] = self.cuota
        if self.reintentar_en_segundos is not None:
            cuerpo["reintentar_en_segundos"] = self.reintentar_en_segundos
        if self.detalles:
            cuerpo["detalles"] = self.detalles
        return cuerpo
