#!/usr/bin/env bash
# Pasos de SISTEMA para usar este equipo como servidor de Xia. Requiere sudo. Es idempotente: se puede repetir.
#
#   sudo deploy/sudo/preparar-servidor.sh                     # prepara el equipo
#   sudo WEB_IP=192.168.2.153 deploy/sudo/preparar-servidor.sh  # además, limita el puerto 8900 a esa IP (si ufw está activo)
#   sudo deploy/sudo/preparar-servidor.sh --si                # sin pedir confirmación
#
# Qué hace:
#   1. Desactiva la suspensión e hibernación del sistema (un servidor dormido no responde).
#   2. Instala Docker Engine nativo (si falta) y lo habilita al arranque. A diferencia de Docker Desktop, NO necesita
#      una sesión gráfica abierta. Convive con Docker Desktop: este usa el contexto "desktop-linux", el Engine "default".
#   3. Añade tu usuario al grupo docker (hay que cerrar sesión y volver a entrar).
#   4. Si ufw está ACTIVO y se indica WEB_IP: permite el puerto 8900 solo desde esa IP y lo cierra al resto.
#      Si ufw está inactivo NO lo activa (con "denegar entrante" cortaría los demás servicios de desarrollo de este
#      equipo, como el Core, el frontend o MBA3): lo avisa para que decidas.
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo "Ejecútalo con sudo."; exit 1; }
USUARIO="${SUDO_USER:-}"
[ -n "$USUARIO" ] && [ "$USUARIO" != "root" ] || { echo "Ejecútalo con 'sudo' desde tu usuario (no como root directo)."; exit 1; }

if [ "${1:-}" != "--si" ]; then
  cat <<TXT
Se va a:
  - enmascarar sleep/suspend/hibernate (el equipo dejará de dormirse),
  - instalar Docker Engine nativo si no está y habilitarlo al arranque,
  - añadir a $USUARIO al grupo docker${WEB_IP:+,
  - limitar el puerto 8900 a $WEB_IP (solo si ufw está activo)}.
TXT
  read -r -p "¿Continuar? [s/N] " r
  [ "$r" = "s" ] || [ "$r" = "S" ] || { echo "Cancelado."; exit 0; }
fi

echo "== 1/4 Suspensión"
systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target
echo "   Suspensión desactivada a nivel de sistema."

echo "== 2/4 Docker Engine"
if command -v dockerd >/dev/null 2>&1; then
  echo "   dockerd ya está instalado."
else
  apt-get update -y
  apt-get install -y ca-certificates curl gnupg
  install -m 0755 -d /etc/apt/keyrings
  if [ ! -f /etc/apt/keyrings/docker.asc ]; then
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
  fi
  if [ ! -f /etc/apt/sources.list.d/docker.list ]; then
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
      > /etc/apt/sources.list.d/docker.list
  fi
  apt-get update -y
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
fi
systemctl unmask docker.service docker.socket containerd.service 2>/dev/null || true
systemctl enable --now containerd docker
echo "   Docker Engine activo y habilitado al arranque."

echo "== 3/4 Grupo docker"
usermod -aG docker "$USUARIO"
echo "   $USUARIO añadido al grupo docker (cierra sesión y vuelve a entrar para que surta efecto)."

echo "== 4/4 Firewall"
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
  if [ -n "${WEB_IP:-}" ]; then
    ufw allow from "$WEB_IP" to any port 8900 proto tcp comment 'Xia: solo el servidor web'
    ufw deny 8900/tcp comment 'Xia: cerrado al resto'
    echo "   Puerto 8900 limitado a $WEB_IP."
  else
    echo "   ufw está activo pero no indicaste WEB_IP: el puerto 8900 sigue la política por defecto."
  fi
else
  echo "   AVISO: ufw no está activo, así que el puerto 8900 quedará abierto a toda la red local."
  echo "   Decide una de: (a) activar ufw con reglas para TODOS tus servicios de desarrollo, (b) filtrar en el router,"
  echo "   o (c) publicar la API solo en 127.0.0.1 y poner un proxy inverso con lista de IP."
fi

cat <<TXT

Siguiente:
  1. Cierra sesión y vuelve a entrar (grupo docker).
  2. cd $(cd "$(dirname "$0")/../.." && pwd) && cp .env.example .env   # y completa XIA_DB_PASSWORD, XIA_JWT_SECRET, etc.
  3. deploy/instalar-usuario.sh --servidor
  4. docker --context default compose -f docker-compose.servidor.yml up -d --build
  5. deploy/verificar-servidor.sh
TXT
