# Xia

Asistente de IA de SCNexus (reemplazo propio de mIA). RAG sobre documentación organizacional: responde
**solo** con lo que dice la documentación, cita las fuentes y dice "no sé" cuando no la cubre.

Estado: **nivel 1** (RAG con búsqueda híbrida). Primera área indexada: `odc-mba3` (docs de `api-odc-mba3`).
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

Todo en Docker: `docker compose --profile app up -d` (la API usa red del host para alcanzar Ollama).

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
| qwen3:8b | 12 | 1 | 1 | 4/4 | 1,9 s |
| gemma3:12b | 11 | 0 | 3 | 3/4 | 3,2 s |
| qwen2.5:7b-instruct | 10 | 3 | 1 | 4/4 | 1,6 s |
| mistral:latest | 6 | 5 | 3 | 4/4 | 2,1 s |
| llama3:latest | 4 | 10 | 0 | 4/4 | 1,4 s |

La muestra es pequeña y la escribió quien armó el pipeline: sirve para descartar (llama3 y mistral) y para
orientar, **no** para afirmar que qwen3 sea "el mejor". Ampliar con preguntas reales de usuarios.

## Pendiente conocido

- La recuperación falla en 1 de 14 (`estado-inicial`: la pregunta está redactada muy distinto al documento). Candidatos: reranker, reformulación de la pregunta, `top_k` mayor.
- Gemma3 no rechazó "¿cuántas órdenes hay pendientes hoy?" y propuso una consulta SQL inventada: justo el caso de datos en vivo (nivel 4), que requiere herramientas con permisos, no más RAG.
- Los permisos por área aún no existen: hoy todo usuario ve todas las áreas.
- Solo se indexan `.md`; los PDF/XLSX de `docs/` quedan fuera. Las tablas Markdown muy largas se parten por filas.
- La cuota y la auditoría no tienen autenticación: `usuario_ad` lo envía el cliente (igual que mIA hoy).
