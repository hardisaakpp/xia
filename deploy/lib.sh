#!/usr/bin/env bash
# Funciones comunes de los scripts de operación de Xia. Se cargan con `. lib.sh`; no se ejecuta directamente.
#
# Configuración opcional en ~/.config/xia/servidor.env (ver deploy/env.servidor.example). Sin ese archivo se usan los
# valores por defecto, pensados para el equipo de desarrollo con Docker Desktop.

XIA_DIR_DEFECTO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_SERVIDOR="${XIA_ENV_SERVIDOR:-$HOME/.config/xia/servidor.env}"
# shellcheck disable=SC1090
[ -f "$ENV_SERVIDOR" ] && . "$ENV_SERVIDOR"

XIA_DIR="${XIA_DIR:-$XIA_DIR_DEFECTO}"
XIA_COMPOSE="${XIA_COMPOSE:-docker-compose.yml}"
XIA_PROJECT="${XIA_PROJECT:-xia}"
XIA_URL="${XIA_URL:-http://127.0.0.1:8900}"
OLLAMA_URL="${OLLAMA_URL:-http://127.0.0.1:11434}"
XIA_RESPALDO_DIR="${XIA_RESPALDO_DIR:-$HOME/respaldos/xia}"
XIA_RESPALDO_DIAS="${XIA_RESPALDO_DIAS:-14}"
XIA_ESTADO_DIR="${XIA_ESTADO_DIR:-$HOME/.local/state/xia}"
XIA_MODELOS="${XIA_MODELOS:-qwen3:8b bge-m3}"

# docker con el contexto elegido (Docker Desktop = desktop-linux; Docker Engine nativo = default).
dk() { docker ${XIA_DOCKER_CONTEXT:+--context "$XIA_DOCKER_CONTEXT"} "$@"; }

log() { printf '%s %s\n' "$(date '+%F %T')" "$*"; }

# Id del contenedor de un servicio del compose de Xia (db, api); vacío si no existe.
contenedor() {
  dk ps -q --filter "label=com.docker.compose.project=$XIA_PROJECT" --filter "label=com.docker.compose.service=$1" | head -n1
}

# Avisa por el diario del sistema, por notificación de escritorio (si hay sesión) y por webhook (si está configurado).
alertar() {
  local mensaje="$1"
  logger -t xia "$mensaje" 2>/dev/null || true
  if command -v notify-send >/dev/null 2>&1 && [ -S "/run/user/$(id -u)/bus" ]; then
    DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$(id -u)/bus" notify-send -u critical "Xia" "$mensaje" 2>/dev/null || true
  fi
  if [ -n "${XIA_ALERTA_WEBHOOK:-}" ]; then
    # Formato {"text": ...}: lo aceptan Slack y los conectores de Teams. Si el servicio pide otro, ajustar aquí.
    curl -fsS --max-time 10 -H 'Content-Type: application/json' \
      -d "$(printf '{"text": "Xia (%s): %s"}' "$(hostname)" "$mensaje" | sed 's/\\/\\\\/g;s/\n/ /g')" \
      "$XIA_ALERTA_WEBHOOK" >/dev/null 2>&1 || true
  fi
}
