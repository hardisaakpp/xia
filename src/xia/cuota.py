"""Cuota por usuario en ventana deslizante, calculada sobre la tabla de auditoría `consultas`."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from xia import db
from xia.config import get_settings


def consultar(usuario_ad: str) -> dict[str, Any]:
    s = get_settings()
    ventana = timedelta(hours=s.cuota_ventana_horas)
    ahora = datetime.now(timezone.utc)
    with db.pool().connection() as conn:
        usadas, mas_antigua = conn.execute(
            "SELECT count(*), min(creada) FROM consultas "
            "WHERE usuario_ad = %s AND error IS NULL AND intencion IS DISTINCT FROM 'charla' AND creada > now() - %s",
            (usuario_ad, ventana),
        ).fetchone()

    renueva = (mas_antigua or ahora) + ventana
    restantes = max(s.cuota_limite - usadas, 0)
    return {
        "limite": s.cuota_limite,
        "usadas": usadas,
        "restantes": restantes,
        "porcentaje_disponible": round(restantes * 100 / s.cuota_limite),
        "renueva": renueva.isoformat(),
        "renueva_en_segundos": max(int((renueva - ahora).total_seconds()), 0),
        "advertencia": restantes <= s.cuota_limite * 0.10,
    }
