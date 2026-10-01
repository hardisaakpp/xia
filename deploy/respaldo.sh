#!/usr/bin/env bash
# Respaldo de la base de Xia (pg_dump formato custom) con verificación y rotación.
#
# Lo único irrecuperable es el historial de consultas (auditoría y cuotas): el índice se reconstruye desde los
# documentos con `python -m xia.indexer`. Se respalda la base completa porque es pequeña y evita reindexar al restaurar.
#
# Restaurar:  docker exec -i <contenedor-db> pg_restore -U xia -d xia --clean --if-exists < archivo.dump
set -euo pipefail
. "$(dirname "$0")/lib.sh"

db="$(contenedor db)"
if [ -z "$db" ]; then
  alertar "Respaldo fallido: no hay contenedor de base de datos de Xia en ejecución."
  exit 1
fi

mkdir -p "$XIA_RESPALDO_DIR"
chmod 700 "$XIA_RESPALDO_DIR"
archivo="$XIA_RESPALDO_DIR/xia-$(date +%Y%m%d-%H%M%S).dump"

if ! dk exec "$db" pg_dump -U xia -d xia -Fc > "$archivo.tmp"; then
  rm -f "$archivo.tmp"
  alertar "Respaldo fallido: pg_dump terminó con error."
  exit 1
fi

# Un respaldo que no se puede leer no sirve: se comprueba antes de aceptarlo.
if ! dk exec -i "$db" pg_restore -l < "$archivo.tmp" > /dev/null 2>&1; then
  rm -f "$archivo.tmp"
  alertar "Respaldo fallido: el archivo generado no es legible por pg_restore."
  exit 1
fi

mv "$archivo.tmp" "$archivo"
chmod 600 "$archivo"
find "$XIA_RESPALDO_DIR" -name 'xia-*.dump' -mtime +"$XIA_RESPALDO_DIAS" -delete
log "Respaldo OK: $archivo ($(du -h "$archivo" | cut -f1)); se conservan $XIA_RESPALDO_DIAS días."
