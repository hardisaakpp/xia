#!/usr/bin/env bash
# Comprueba que este equipo está listo para servir Xia. Úsalo tras preparar el servidor y TRAS CADA REINICIO.
# Sale con 0 si todo pasa y con 1 si algo falla; imprime qué arreglar.
set -uo pipefail
. "$(dirname "$0")/lib.sh"

fallos=0
ok()   { printf '  \033[32m✔\033[0m %s\n' "$1"; }
mal()  { printf '  \033[31m✘\033[0m %s\n      → %s\n' "$1" "$2"; fallos=$((fallos + 1)); }
aviso(){ printf '  \033[33m!\033[0m %s\n      → %s\n' "$1" "$2"; }

echo "Energía"
if systemctl is-enabled suspend.target 2>/dev/null | grep -q masked; then ok "La suspensión está desactivada a nivel de sistema"
else mal "El sistema puede suspenderse" "sudo deploy/sudo/preparar-servidor.sh"; fi

echo "Docker"
if systemctl is-enabled docker 2>/dev/null | grep -q enabled && systemctl is-active docker 2>/dev/null | grep -q '^active'; then ok "Docker Engine arranca con el sistema y está activo"
else mal "Docker Engine nativo no está activo y habilitado" "sudo deploy/sudo/preparar-servidor.sh (si se usa Docker Desktop, no arranca sin sesión gráfica)"; fi
if [ -z "${XIA_DOCKER_CONTEXT:-}" ]; then aviso "XIA_DOCKER_CONTEXT sin definir (se usa el contexto actual: $(docker context show 2>/dev/null))" "deploy/instalar-usuario.sh --servidor"; fi

echo "Xia"
db="$(contenedor db)"; api="$(contenedor api)"
[ -n "$db" ] && [ "$(dk inspect -f '{{.State.Health.Status}}' "$db" 2>/dev/null)" = "healthy" ] && ok "Base de datos sana" || mal "La base de datos de Xia no está sana" "cd $XIA_DIR && docker ${XIA_DOCKER_CONTEXT:+--context $XIA_DOCKER_CONTEXT} compose -f $XIA_COMPOSE up -d"
[ -n "$api" ] && [ "$(dk inspect -f '{{.State.Health.Status}}' "$api" 2>/dev/null)" = "healthy" ] && ok "API sana" || mal "La API de Xia no está sana" "revisa: docker logs <contenedor api>"
curl -fsS --max-time 5 "$XIA_URL/v1/salud" >/dev/null 2>&1 && ok "GET /v1/salud responde" || mal "GET /v1/salud no responde" "revisa XIA_URL=$XIA_URL y los logs de la API"
code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 -X POST "$XIA_URL/v1/preguntar" -H 'Content-Type: application/json' -d '{"pregunta":"hola"}')"
[ "$code" = "401" ] && ok "Sin token, la API rechaza (401): la autenticación JWT está activa" || mal "Sin token la API respondió $code (se esperaba 401)" "XIA_AUTENTICACION debe ser 'jwt' en el servidor"

echo "Ollama (modelos para la GPU)"
curl -fsS --max-time 5 "$OLLAMA_URL/api/tags" >/dev/null 2>&1 && ok "Ollama responde" || mal "Ollama no responde" "systemctl status ollama"
for m in $XIA_MODELOS; do curl -fsS --max-time 5 "$OLLAMA_URL/api/tags" 2>/dev/null | grep -q "\"name\":\"$m" && ok "Modelo $m disponible" || mal "Falta el modelo $m" "ollama pull $m"; done
systemctl is-enabled ollama 2>/dev/null | grep -q enabled && ok "Ollama arranca con el sistema" || mal "Ollama no arranca con el sistema" "sudo systemctl enable ollama"

echo "Operación"
[ "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null)" = "yes" ] && ok "Sesión persistente (linger) activa" || mal "Sin linger: los temporizadores no corren sin sesión" "loginctl enable-linger $USER"
for t in xia-respaldo xia-vigilar; do systemctl --user is-active "$t.timer" 2>/dev/null | grep -q '^active' && ok "Temporizador $t activo" || mal "Temporizador $t inactivo" "deploy/instalar-usuario.sh"; done
ultimo="$(ls -t "$XIA_RESPALDO_DIR"/xia-*.dump 2>/dev/null | head -1)"
if [ -n "$ultimo" ] && [ -n "$(find "$ultimo" -mtime -2 2>/dev/null)" ]; then ok "Hay un respaldo de las últimas 48 h ($(basename "$ultimo"))"
else aviso "No hay respaldo reciente en $XIA_RESPALDO_DIR" "deploy/respaldo.sh"; fi

echo "Red"
ip_local="$(hostname -I | awk '{print $1}')"
metodo="$(nmcli -g ipv4.method con show --active 2>/dev/null | head -1)"
[ "$metodo" = "manual" ] && ok "IP fija ($ip_local)" || aviso "La IP ($ip_local) la asigna DHCP y puede cambiar" "reserva esa IP en el router (por MAC) o fíjala en el equipo; la web de producción apunta a ella"
echo "  (Que el servidor web de producción alcance $ip_local:8900 solo se puede comprobar DESDE ese servidor: curl http://$ip_local:8900/v1/salud)"

echo
[ "$fallos" -eq 0 ] && echo "Todo en orden." || echo "$fallos comprobación(es) fallida(s)."
exit $((fallos > 0))
