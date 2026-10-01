# Xia

Asistente de IA de SCNexus (reemplazo propio de mIA). RAG sobre documentación organizacional: responde
**solo** con lo que dice la documentación, cita las fuentes y dice "no sé" cuando no la cubre.

Estado: **nivel 2 completo, nivel 3 (multi-fuente) en curso** (búsqueda híbrida, memoria con reformulación, charla natural). Áreas: `odc-mba3`, `promocion-sobres`, `core-scnexus`, `middleware-sap`, `scnexus-manuales`, `scnexus-frontend`.
Contrato HTTP compatible con mIA (`web-scnexus/src/services/miaApi.ts`): Cool-turito puede consumirlo sin cambios.

## Puesta en marcha (Ubuntu)

```bash
docker compose up -d db                 # PostgreSQL + pgvector en 127.0.0.1:5433
ollama pull bge-m3 && ollama pull qwen3:8b
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'

.venv/bin/python -m xia.indexer         # indexa las áreas de sources.yaml (incremental)
.venv/bin/uvicorn xia.api:app --port 8900

curl -s localhost:8900/v1/preguntar -H 'Content-Type: application/json' \
  -d '{"usuario_ad":"tu.usuario","pregunta":"¿Qué estado tiene un pedido si falla el envío a SAP?"}'
```

Todo en Docker (API en `127.0.0.1:8900`, con reinicio automático tras reiniciar el equipo):

```bash
docker compose --profile app up -d --build
```

Ollama sigue corriendo en el equipo para usar la GPU; el contenedor lo alcanza por `host.docker.internal`. Tras
cambiar código hay que reconstruir (`--build`). Este equipo usa **Docker Desktop**, que corre los contenedores en
una VM: por eso no se usa `network_mode: host` (el "host" sería la VM y el puerto no sería visible).

## Endpoints

| Ruta | Descripción |
|---|---|
| `POST /v1/preguntar` | `{usuario_ad, pregunta, areas?}` → `{respuesta, fuentes, sin_contexto, modelo, ms, traza_id, cuota}` |
| `GET /v1/areas` | Áreas y si tienen documentos |
| `GET /v1/cuota?usuario_ad=` | Cuota sin consumirla |
| `GET /v1/salud` | `{ok: true}` |

Errores: `{error, message, traza_id?, cuota?, detalles?}`. El frontend decide por `error` (`cuota-agotada`,
`sin-modelo`, `peticion-invalida`, `area-no-permitida`, `sin-areas`, `sin-indice`, `demasiadas-peticiones`,
`error-interno`), no por el status.

## Cómo funciona

```
pregunta → embedding (bge-m3) → recuperación híbrida (vectores + texto, fusión RRF)
         → ¿mejor similitud ≥ umbral? no → sin_contexto (sin gastar LLM)
         → LLM con solo los fragmentos → cita [n] → fuentes → auditoría (traza_id)
```

- `sources.yaml`: catálogo de áreas. **Un módulo nuevo = una entrada nueva + reindexar**; el pipeline no cambia.
- El modelo es configuración (`XIA_MODELO_GENERACION`), no código. `src/xia/llm.py` es la única pieza que habla con Ollama.
- Cuota por usuario en ventana deslizante, calculada sobre la tabla de auditoría `consultas`.

## Evaluación (hacerla antes de cambiar modelo, prompt o umbral)

```bash
.venv/bin/python eval/run_eval.py --modelos qwen3:8b,gemma3:12b
```

`eval/preguntas.yaml` es un **borrador** de 18 preguntas (14 con respuesta, 4 que Xia debe rechazar). Mide
recuperación y generación por separado, y distingue "se negó sin motivo" de "respondió mal con seguridad".

Primera comparación (2026-09-30, RTX 3060 12 GB, 14 preguntas con respuesta):

| Modelo | Correctas | Falsos rechazos | Respuestas incorrectas | Rechazos ok | Mediana |
|---|---:|---:|---:|---:|---:|
| qwen3:8b | 13 (12 antes del ajuste de recuperación) | 0 | 1 | 4/4 | 1,9 s |
| gemma3:12b | 11 | 0 | 3 | 3/4 | 3,2 s |
| qwen2.5:7b-instruct | 10 | 3 | 1 | 4/4 | 1,6 s |
| mistral:latest | 6 | 5 | 3 | 4/4 | 2,1 s |
| llama3:latest | 4 | 10 | 0 | 4/4 | 1,4 s |

Los demás modelos se midieron con la recuperación anterior (13/14); con la actual, la recuperación acierta 14/14.

La muestra es pequeña y la escribió quien armó el pipeline: sirve para descartar (llama3 y mistral) y para
orientar, **no** para afirmar que qwen3 sea "el mejor". Ampliar con preguntas reales de usuarios.

## Mantener la documentación al día

Xia solo sabe lo que dicen los documentos indexados (`sources.yaml`), así que **la documentación desactualizada produce
respuestas desactualizadas**. Tres de los documentos de `api-odc-mba3/docs` se generan desde la fuente de verdad:

```bash
cd ../api-odc-mba3
python scripts/generar_referencia_api.py          # docs/REFERENCIA_API.md  (desde el OpenAPI del servicio en :8000)
python scripts/generar_catalogo_migraciones.py    # docs/CATALOGO_MIGRACIONES.md  (desde migrations_manifest.yaml)
docker exec -i mba3-api python - < scripts/generar_esquema_bd.py > docs/ESQUEMA_BD.md   # tablas y columnas de la BD real
cd ../xia && .venv/bin/python -m xia.indexer      # reindexa solo lo que cambió
```

El **manual de usuario** (`docs/Manual_del_usuario/*.md`) se mantiene a mano y es la fuente de las respuestas de tipo
"¿cómo hago…?": al cambiar una pantalla, actualizarlo y reindexar. Última revisión: 01/10/2026, contrastada con el
código del frontend. Tras reindexar conviene correr `eval/run_eval.py` para detectar respuestas que dejaron de salir bien.

## Charla y negativas

Antes de buscar en la documentación, `src/xia/intencion.py` detecta **charla** (saludos, gracias, despedidas, "¿quién
eres?", "¿qué puedes hacer?") en tres zonas según la similitud del embedding con unas frases de ejemplo: muy parecido →
charla sin gastar el modelo; nada parecido → consulta; en medio (solo mensajes de hasta 8 palabras) → el modelo decide
con una llamada de una palabra. La charla se responde natural, **no cita fuentes ni consume cuota**, y se decide con el
mensaje original (antes de reformular con el historial).

Cuando algo queda fuera de alcance, la negativa orienta: dice de qué temas sí puede hablar y sugiere una pregunta de
ejemplo (`ejemplos:` de cada área en `sources.yaml`).

`eval/calibrar_charla.py` mide el clasificador con frases que NO están entre los ejemplos: 23/23 charla detectada y
0/25 consultas cortas tomadas por charla (2026-10-01). Con la similitud sola no hay umbral que separe ("ayuda con SAP"
puntúa más alto que "súper"), de ahí las tres zonas.

## Reranker (implementado, apagado)

`XIA_RERANKER=cross-encoder` reordena 20 candidatos con `BAAI/bge-reranker-v2-m3` (requiere `pip install .[rerank]` y PyTorch).
Medido con `eval/run_retrieval.py` sobre `eval/recuperacion_dificil.yaml` (16 preguntas coloquiales, 2026-10-01):

| | hit@1 | hit@6 | MRR | Latencia de búsqueda |
|---|---:|---:|---:|---:|
| Sin reranker | 11/16 | 15/16 | 0,792 | 125 ms |
| Con reranker (CPU, 12 núcleos) | 13/16 | 15/16 | 0,875 | 13 200 ms |

Mejora el **orden** pero no la **cobertura** (hit@6 igual), y al generador le llegan los 6 fragmentos de todos modos,
así que el orden pesa poco; a cambio cuesta ~13 s en CPU. Por eso queda apagado. Reconsiderar si hay GPU disponible
para el reranker (el contenedor de Docker Desktop no la tiene) o si se pasa a `top_k` menores.

La falla que queda ("pruebas automáticas antes de subir cambios" → `TESTING.md`) es de **cobertura**: ese documento está en
la posición 56 por significado, fuera de los 20 candidatos, y un reranker no puede rescatar lo que no está entre ellos.
El siguiente paso para eso es mejorar la recuperación de candidatos (más candidatos, expansión de la pregunta), no reordenar.

## Pendiente conocido

- Con identificadores (números de migración, códigos) la búsqueda por texto sola fallaba: ahora se garantizan hasta 2 fragmentos que contengan el identificador exacto (`tokens_exactos`).
- La recuperación acierta 33/35 en `eval/preguntas.yaml` (respuestas 35/35) y 15/16 en el banco difícil, aunque en este último el orden empeoró al crecer el corpus (hit@1 8/16, antes 11/16): hay más documentos legítimos compitiendo por el primer lugar. Corregido: Corregido: la fusión RRF descartaba el mejor resultado vectorial; ahora `XIA_VECTORIALES_GARANTIZADOS` (3) lo asegura.
- Gemma3 no rechazó "¿cuántas órdenes hay pendientes hoy?" y propuso una consulta SQL inventada: justo el caso de datos en vivo (nivel 4), que requiere herramientas con permisos, no más RAG.
- Los permisos por área aún no existen: hoy todo usuario ve todas las áreas.
- Solo se indexan `.md`; los PDF/XLSX de `docs/` quedan fuera. Las tablas Markdown muy largas se parten por filas.
- La cuota y la auditoría no tienen autenticación: `usuario_ad` lo envía el cliente (igual que mIA hoy).

## Seguridad al indexar

Xia responde a cualquier usuario del chat y aún no filtra por permisos de área: **lo que se indexa se puede preguntar**.
- `src/xia/redaccion.py` enmascara el valor de contraseñas, secretos, claves de API y tokens JWT (formatos `clave = "valor"`, `CLAVE=valor`, cadenas de conexión y Markdown `**Password:** \`valor\``) antes de trocear y de calcular embeddings. Se conserva la clave: "la contraseña va en `password`" sigue siendo documentación válida.
- En `sources.yaml` se excluyen los documentos de despliegue, infraestructura, CI/CD, mapas de red y políticas de revisión de código, y los manuales superados.
- Si agregas una fuente nueva, revisa qué contiene antes de indexarla y añade casos `no_contiene` a `eval/preguntas.yaml`.
- Limitación: la redacción es por patrones; no detecta un secreto escrito en prosa ("la clave es Abc123"). Las IPs de servidores no se enmascaran.

## Identidad y permisos por área

Xia **no confía en el cuerpo de la petición**: identifica al usuario con el JWT de SCNexus Core (`Authorization: Bearer`), validado con la misma clave, emisor y audiencia que usan `api-odc-mba3` y `api-cromos` (`XIA_JWT_*`, ver `.env.example`).

| Situación | Resultado |
|---|---|
| Sin token, token vencido o con firma/emisor/audiencia incorrectos | 401 `no-autenticado` |
| Token válido pero sin permisos que habiliten ninguna documentación | 403 `sin-acceso` |
| Pide un área que no puede ver | 403 `area-no-permitida` |
| Rol `Admin` | ve todas las áreas |

- Cada **documento** guarda los permisos que lo habilitan (`documentos.permisos`), declarados en `sources.yaml` (`permisos` por área o `permisos_por_patron` por documento). Basta **uno** de ellos; `modulo.*` es un prefijo y `*` admite a cualquier usuario autenticado. **Sin permisos declarados, solo lo ve un Admin** (denegar por defecto).
- La búsqueda filtra en SQL por los documentos permitidos: el modelo nunca recibe fragmentos que el usuario no puede leer. `/v1/areas`, el catálogo de la charla y el mensaje de "no encontré" solo nombran las áreas visibles.
- La cuota y la auditoría usan el usuario **del token**, no `usuario_ad`.
- Correspondencia actual: `odc-mba3` ← `odcsap.view`, `produccion-elrayo.view`, `mabel.view`; `promocion-sobres` ← `promocion.sobres.*`, `boton-monitorear.view`; `core-scnexus`, `middleware-sap`, `scnexus-frontend` ← **`xia.tecnico`**; cada manual de `scnexus-manuales` ← los permisos de su módulo (`inventario.*`, `cajachica.*`, `recepcion.*`…).
- **Crear `xia.tecnico` en el Core:** `POST /api/Permissions` (clave `xia.tecnico`, módulo `xia`) y luego `POST /api/Permissions/assign` al rol o usuarios desarrolladores. El token trae el permiso en el siguiente login (los tokens duran 3 h).
- Los permisos de un documento se actualizan al correr `python -m xia.indexer`; la API los lee con un caché de 30 s.
- `XIA_AUTENTICACION=ninguna` desactiva todo esto y concede acceso total: **solo desarrollo local**. Con `jwt` y sin `XIA_JWT_SECRET`, la API no arranca.
- Evaluación: las preguntas `acc-*` de `eval/preguntas.yaml` se ejecutan con un `perfil` de permisos y comprueban que cada área solo responde a quien corresponde (y que la charla y los rechazos no delatan áreas ocultas).
