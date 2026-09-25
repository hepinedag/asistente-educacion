from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent.parent
ENV_PATH = PROJECT_ROOT / "config" / ".env"


class Settings(BaseSettings):
    environment: str = "development"
    cors_origins: str = "http://localhost:5173"

    database_url: str = "postgresql://postgres:postgres@localhost:5432/asistente_educacion"

    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    llm_provider: str = "claude"
    # 127.0.0.1 y no localhost: Ollama y el servidor de embeddings escuchan solo
    # en IPv4, y en Windows `localhost` prueba antes ::1 y espera ~2 s a fallar.
    # Dentro de Docker manda docker-compose.yml, que fija
    # host.docker.internal; esto rige cuando el backend corre fuera del contenedor.
    ollama_host: str = "http://127.0.0.1:11434"
    ollama_model: str = "gemma4:e2b-it-qat"
    ollama_timeout_seconds: float = 300.0

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"
    anthropic_timeout_seconds: float = 120.0

    embedding_provider: str = "sentence-transformers"
    embedding_model: str = "paraphrase-multilingual-MiniLM-L12-v2"
    embedding_service_url: str = "http://127.0.0.1:8500"

    reranker_provider: str = "cross-encoder"

    chroma_host: str = "localhost"
    chroma_port: int = 8000

    corpus_dir: str = str(PROJECT_ROOT / "corpus" / "fuente")

    model_config = SettingsConfigDict(env_file=ENV_PATH, env_file_encoding="utf-8", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
