# Xia como servidor en este equipo (piloto)

Este documento describe cómo dejar que el equipo de desarrollo, con su GPU, sirva también a Xia, y qué se debe cuidar
mientras comparte ese doble papel. Es un **piloto**: Xia es portable (Docker + variables de entorno), así que pasar a un
servidor dedicado después es copiar la configuración y restaurar un respaldo.

## Estado y decisiones

| Tema | Decisión | Por qué |
|---|---|---|
| Docker | **Docker Engine nativo** para Xia; Docker Desktop sigue para el desarrollo | Docker Desktop exige una sesión gráfica abierta (`Requires=graphical-session.target`): tras un reinicio, Xia no volvería hasta iniciar sesión. El Engine es un servicio del sistema. |
| Red de la API | `network_mode: host` (solo Engine) | Llega a Ollama en `127.0.0.1` sin exponerlo; el puerto 8900 lo filtra el firewall. No sirve en Docker Desktop (corre en una VM). |
| Identidad | JWT del Core (`XIA_AUTENTICACION=jwt`) | Sin token, 401. Necesita la clave `Jwt:Key` **de producción**. |
| Energía | Suspensión desactivada (sistema y escritorio) | Un servidor dormido no responde. |
| Respaldos | Diario 02:30, 14 días, con verificación | El historial de consultas es lo único irrecuperable; el índice se reconstruye. |
| Vigilancia | Cada 2 min; avisa solo al cambiar de estado | Evita alertas repetidas. |

## Qué ya está hecho en este equipo (sin sudo)

- Suspensión desactivada en el escritorio (`gsettings`), Docker Desktop habilitado al inicio de sesión y `linger` activo.
- Temporizadores de usuario `xia-respaldo.timer` y `xia-vigilar.timer` instalados (`deploy/instalar-usuario.sh`).
- La API tiene `healthcheck`; la vigilancia la levanta sola si cae (probado).

## Pasos pendientes (requieren sudo o decisiones tuyas)

1. **Sistema:** `sudo deploy/sudo/preparar-servidor.sh` (añade `WEB_IP=<ip del servidor web>` para limitar el puerto 8900 si
   `ufw` está activo). Instala Docker Engine, enmascara la suspensión y habilita el arranque. Cierra sesión y vuelve a entrar.
2. **Configuración:** `cp .env.example .env` y completa `XIA_DB_PASSWORD` (`openssl rand -hex 16`), `XIA_JWT_SECRET`
   (la `Jwt:Key` del Core de producción), `XIA_JWT_ISSUER` y `XIA_JWT_AUDIENCE`. El `.env` nunca se sube al repositorio.
3. **Operación:** `deploy/instalar-usuario.sh --servidor` (apunta los scripts al Engine y al compose de servidor).
4. **Arrancar:** `docker --context default compose -f docker-compose.servidor.yml up -d --build`.
5. **Datos:** o bien reindexar (`XIA_DATABASE_URL=postgresql://xia:<clave>@127.0.0.1:5433/xia python -m xia.indexer`), o
   restaurar el último respaldo conservando el historial:
   `docker --context default exec -i xia-db-1 pg_restore -U xia -d xia --clean --if-exists < ~/respaldos/xia/<archivo>.dump`
6. **Comprobar:** `deploy/verificar-servidor.sh`. Repetirlo **después de reiniciar el equipo**, que es la prueba real.
7. **Red:**
   - Reservar la IP de este equipo en el router (por MAC) o fijarla, para que no cambie.
   - Desde el **servidor web de producción** debe funcionar `curl http://<IP-de-este-equipo>:8900/v1/salud`.
   - En el servidor web, definir `UPSTREAM_MIA=http://<IP-de-este-equipo>:8900` y recargar nginx. La plantilla
     `deploy/nginx/scnexus-docker.conf.template` ya reenvía `Authorization` y tiene timeouts de 180 s: no hay que cambiarla.

## Riesgos de compartir el equipo (y cómo se mitigan)

- **GPU:** Ollama mantiene ~7,6 GB de los 12 GB de VRAM. Si tu trabajo con GPU necesita más, el modelo se descarga y Xia
  se vuelve lenta o responde 429 («ocupado»). Xia atiende una pregunta a la vez (`XIA_MAX_CONCURRENTES=1`).
- **Reinicios y actualizaciones:** un reinicio corta el servicio unos minutos. Evita reiniciar en horario de uso.
- **Documentos publicados:** el indexador lee los **archivos de trabajo** de los repos de este equipo. Un borrador sin
  commit llegaría a Xia. Antes de abrir el servicio a todos, indexar desde copias limpias de las ramas publicadas.
- **Seguridad:** el equipo guarda código y credenciales de desarrollo. La API pide JWT, pero limita el puerto a la IP del
  servidor web y no reutilices la contraseña de la base ni la clave JWT de desarrollo.
- **Punto único de fallo:** si el equipo se apaga, Xia cae (el widget muestra «no se pudo conectar»). Es aceptable en un
  piloto; para producción real, un servidor dedicado.

## Operación

| Qué | Cómo |
|---|---|
| Estado | `deploy/verificar-servidor.sh` |
| Respaldo manual | `deploy/respaldo.sh` (archivos en `~/respaldos/xia`) |
| Probar una restauración | restaurar en una base temporal con `pg_restore` y comparar conteos (probado: 95 docs, 1 959 fragmentos, 28 consultas idénticos) |
| Logs de los temporizadores | `journalctl --user -u xia-vigilar -u xia-respaldo` |
| Alertas | diario del sistema + notificación de escritorio; webhook opcional (`XIA_ALERTA_WEBHOOK` en `~/.config/xia/servidor.env`) |
| Desinstalar temporizadores | `deploy/instalar-usuario.sh --quitar` |

## Lo que NO se pudo probar aquí

- `docker-compose.servidor.yml` y `deploy/sudo/preparar-servidor.sh`: requieren Docker Engine, que no está instalado. El
  compose se valida con `docker compose config`, pero su arranque real, el acceso a Ollama por `127.0.0.1` y el firewall
  quedan por verificar con `deploy/verificar-servidor.sh` tras el paso 4.
- El alcance desde el servidor web de producción: este equipo está en `192.168.100.0/24` y no tiene ruta a
  `192.168.2.x`, `172.30.x` ni `210.17.x` (comprobado el 01/10/2026).
