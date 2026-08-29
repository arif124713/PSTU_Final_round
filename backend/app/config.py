from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    app_name: str = "MoneyMove"
    app_env: str = "development"
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440
    refresh_token_expire_days: int = 30

    database_url: str
    db_pool_size: int = 20
    db_max_overflow: int = 10

    redis_url: str = "redis://localhost:6379/0"

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    deepseek_max_tokens: int = 1000

    mcp_server_url: str = "http://localhost:8001"
    db_mcp_password: str = ""

    chroma_persist_path: str = "./chroma_db"
    chroma_collection: str = "support_docs"

    rag_docs_path: str = "./data/rag_docs"

    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    max_single_transfer_bdt: int = 25_000
    daily_transfer_limit_bdt: int = 100_000
    cooldown_seconds: int = 600
    pin_max_attempts: int = 3
    pin_lock_seconds: int = 900
    velocity_max_transfers: int = 5
    velocity_window_seconds: int = 600
    unusual_amount_threshold: int = 10_000
    starter_balance_bdt: int = 100_000
    dispute_window_days: int = 7


settings = Settings()
