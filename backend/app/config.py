from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Keys and config, read from the environment (or a .env file at the project root)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    anthropic_api_key: str
    voyage_api_key: str
    pinecone_api_key: str
    pinecone_index: str = "feeling-is-the-secret"


settings = Settings()
