#!/usr/bin/env bash
# Vigilancia de Xia: comprueba la API y Ollama, intenta levantar los contenedores si la API no responde y avisa
# cuando el estado CAMBIA (cae o se recupera), sin repetir la alerta en cada ejecución.
#
# Sale con 0 si todo está bien y con 1 si algo falla (útil para `systemctl --user status xia-vigilar`).
set -uo pipefail
. "$(dirname "$0")/lib.sh"

mkdir -p "$XIA_ESTADO_DIR"
estado_previo="$(cat "$XIA_ESTADO_DIR/estado" 2>/dev/null || echo ok)"
fallos=()

comprobar() {
  fallos=()
  curl -fsS --max-time 6 "$XIA_URL/v1/salud" >/dev/null 2>&1 || fallos+=("La API de Xia no responde en $XIA_URL/v1/salud")
  local tags
  if tags="$(curl -fsS --max-time 6 "$OLLAMA_URL/api/tags" 2>/dev/null)"; then
    local m
    for m in $XIA_MODELOS; do
      grep -q "\"name\":\"$m" <<<"$tags" || fallos+=("Ollama no tiene el modelo $m")
    done
  else
    fallos+=("Ollama no responde en $OLLAMA_URL")
  fi
}

comprobar
if [ "${#fallos[@]}" -gt 0 ] && printf '%s\n' "${fallos[@]}" | grep -q "API de Xia"; then
  # Un solo intento de recuperación: levantar lo que esté caído (no recrea lo que ya corre).
  log "La API no responde; intentando levantar los contenedores…"
  # La API del compose de desarrollo está en el perfil "app"; el de servidor no usa perfiles (la variable no le afecta).
  (cd "$XIA_DIR" && COMPOSE_PROFILES="${COMPOSE_PROFILES:-app}" dk compose -f "$XIA_COMPOSE" up -d >/dev/null 2>&1) || true
  sleep 25
  comprobar
fi

if [ "${#fallos[@]}" -eq 0 ]; then
  echo ok > "$XIA_ESTADO_DIR/estado"
  if [ "$estado_previo" = "falla" ]; then
    alertar "Xia se recuperó: la API y Ollama responden de nuevo."
  fi
  log "OK"
  exit 0
fi

echo falla > "$XIA_ESTADO_DIR/estado"
detalle="$(printf '%s; ' "${fallos[@]}")"
log "FALLA: $detalle"
# Solo se avisa al pasar de ok a falla; mientras siga caído no se insiste.
if [ "$estado_previo" != "falla" ]; then
  alertar "Xia tiene problemas: ${detalle%; }"
fi
exit 1
