from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    groq_api_key: str = ""
    openrouter_api_key: str = ""
    gemini_api_key: str = ""
    tavily_api_key: str = ""
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    embed_model: str = "all-MiniLM-L6-v2"
    collection_name: str = "codebase_chunks"
    groq_model: str = "openai/gpt-oss-120b"
    openrouter_model: str = "meta-llama/llama-3.3-70b-instruct:free"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()