from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuración por variables de entorno `XIA_*` (o archivo .env). El modelo es configuración, no código."""

    model_config = SettingsConfigDict(env_prefix="XIA_", env_file=".env", extra="ignore")

    database_url: str = "postgresql://xia:xia@127.0.0.1:5433/xia"
    ollama_url: str = "http://127.0.0.1:11434"
    modelo_generacion: str = "qwen3:8b"
    modelo_embeddings: str = "bge-m3"
    dim_embeddings: int = 1024
    ollama_num_ctx: int = 6144
    # Modelos con modo "pensar" (qwen3, ...): apagado por defecto, multiplica la latencia en consultas con contexto.
    pensar: bool = False
    timeout_llm_s: float = 120.0
    # Cuánto mantiene Ollama los modelos en VRAM tras la última llamada. Como servidor, conviene largo: recargarlos
    # tras un rato sin uso suma varios segundos a la primera pregunta.
    ollama_keep_alive: str = "30m"

    # Nombre con el que Xia se presenta ("el asistente de {organizacion}"). Cada despliegue pone el suyo.
    organizacion: str = "SCNEXUS"

    sources_file: str = "sources.yaml"
    max_chars_fragmento: int = 1500

    top_k: int = 6
    # Detección de charla (calibrar con eval/calibrar_charla.py): por encima de `seguro` es charla sin más; por debajo de
    # `dudoso` es consulta; en medio (y solo en mensajes cortos) decide el modelo con una llamada breve.
    umbral_charla_seguro: float = 0.80
    umbral_charla_dudoso: float = 0.50
    # Reordenamiento fino de los candidatos: "ninguno" o "cross-encoder" (requiere `pip install .[rerank]`).
    reranker: str = "ninguno"
    modelo_reranker: str = "BAAI/bge-reranker-v2-m3"
    candidatos_rerank: int = 20  # cuántos candidatos recupera la búsqueda para que el reranker elija los top_k
    # De los top_k fragmentos, cuántos son siempre los mejores por similitud vectorial (el resto, por fusión híbrida).
    vectoriales_garantizados: int = 3
    # Similitud coseno mínima del mejor fragmento para intentar responder; por debajo = sin_contexto
    # sin llamar al LLM. Es un punto de partida: calibrarlo con eval/run_eval.py.
    umbral_relevancia: float = 0.45

    # Identidad y permisos. "jwt" = el token de SCNexus Core en `Authorization: Bearer` (misma clave, emisor y audiencia
    # que usan api-odc-mba3 y api-cromos); "ninguna" = SOLO desarrollo: confía en `usuario_ad` y concede todo.
    autenticacion: str = "jwt"
    jwt_secret: str = ""
    jwt_issuer: str = ""
    jwt_audience: str = ""
    roles_admin: list[str] = ["Admin"]  # ven todas las áreas
    permiso_tecnico: str = "xia.tecnico"

    # Agente (herramientas): cuánto de la conversación y de cada resultado de herramienta se entrega al modelo. El contexto
    # es corto a propósito: cambiarlo recarga el modelo en la GPU y encarece la primera respuesta.
    agente_max_mensajes: int = 14
    agente_max_chars_herramienta: int = 4000

    cuota_limite: int = 30
    cuota_ventana_horas: int = 3

    # Una sola GPU: se serializan las generaciones y, si la cola tarda, se responde 429 reintentable.
    max_concurrentes: int = 1
    espera_cola_s: float = 30.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
