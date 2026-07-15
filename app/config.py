from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    gemini_api_key: str = ""
    sentinel_api_key: str = "dev-key"
    log_level: str = "INFO"
    max_reconciliation_rounds: int = 2
    gemini_model: str = "gemini-2.0-flash"
    gemini_lite_model: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
