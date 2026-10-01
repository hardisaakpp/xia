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

    sources_file: str = "sources.yaml"
    max_chars_fragmento: int = 1500

    top_k: int = 6
    # Similitud coseno mínima del mejor fragmento para intentar responder; por debajo = sin_contexto
    # sin llamar al LLM. Es un punto de partida: calibrarlo con eval/run_eval.py.
    umbral_relevancia: float = 0.45

    cuota_limite: int = 30
    cuota_ventana_horas: int = 3

    # Una sola GPU: se serializan las generaciones y, si la cola tarda, se responde 429 reintentable.
    max_concurrentes: int = 1
    espera_cola_s: float = 30.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
