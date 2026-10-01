#!/usr/bin/env bash
# Instala los temporizadores de respaldo y vigilancia como servicios DE USUARIO de systemd. No necesita sudo.
#
#   deploy/instalar-usuario.sh              # equipo de desarrollo con Docker Desktop (valores por defecto)
#   deploy/instalar-usuario.sh --servidor   # servidor con Docker Engine nativo (crea ~/.config/xia/servidor.env)
#   deploy/instalar-usuario.sh --quitar     # desinstala los temporizadores
#
# Para que corran sin que nadie haya iniciado sesión hace falta `loginctl enable-linger $USER` (el script lo intenta).
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
XIA_DIR="$(cd "$DIR/.." && pwd)"
UNIDADES="$HOME/.config/systemd/user"
NOMBRES=(xia-respaldo.service xia-respaldo.timer xia-vigilar.service xia-vigilar.timer)

if [ "${1:-}" = "--quitar" ]; then
  systemctl --user disable --now xia-respaldo.timer xia-vigilar.timer 2>/dev/null || true
  for n in "${NOMBRES[@]}"; do rm -f "$UNIDADES/$n"; done
  systemctl --user daemon-reload
  echo "Temporizadores de Xia desinstalados."
  exit 0
fi

if [ "${1:-}" = "--servidor" ]; then
  mkdir -p "$HOME/.config/xia"
  if [ ! -f "$HOME/.config/xia/servidor.env" ]; then
    cp "$DIR/env.servidor.example" "$HOME/.config/xia/servidor.env"
    echo "Creado ~/.config/xia/servidor.env (contexto Docker 'default' y docker-compose.servidor.yml)."
  fi
fi

mkdir -p "$UNIDADES"
for n in "${NOMBRES[@]}"; do
  sed "s|@XIA_DIR@|$XIA_DIR|g" "$DIR/systemd/$n" > "$UNIDADES/$n"
done
systemctl --user daemon-reload
systemctl --user enable --now xia-respaldo.timer xia-vigilar.timer

if [ "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null)" != "yes" ]; then
  loginctl enable-linger "$USER" 2>/dev/null \
    && echo "Activada la sesión persistente (linger): los temporizadores corren sin iniciar sesión." \
    || echo "AVISO: ejecuta 'sudo loginctl enable-linger $USER' para que los temporizadores corran sin sesión iniciada."
fi
systemctl --user list-timers 'xia-*' --no-pager
