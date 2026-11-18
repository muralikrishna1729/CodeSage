import os
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

class Settings(BaseSettings):
    groq_api_key: str = ""
    openrouter_api_key: str = ""
    gemini_api_key: str = ""
    tavily_api_key: str = ""
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_api_key: str = ""   # only needed for Qdrant Cloud
    qdrant_https: bool = False  # set true for Qdrant Cloud / TLS endpoints
    embed_model: str = "jinaai/jina-embeddings-v2-base-code"
    collection_name: str = "codebase_chunks"
    groq_model: str = "openai/gpt-oss-120b"
    groq_fast_model: str = "openai/gpt-oss-20b"
    openrouter_model: str = "meta-llama/llama-3.3-70b-instruct:free"
    api_key: str = Field(default="", validation_alias="CODESAGE_API_KEY")
    chunk_target_tokens: int = 400
    chunk_overlap_tokens: int = 40
    context_max_tokens: int = 4000

    @model_validator(mode="after")
    def _validate_chunking_and_context(self) -> "Settings":
        if self.chunk_target_tokens <= 0:
            raise ValueError("chunk_target_tokens must be positive")
        if self.chunk_overlap_tokens < 0:
            raise ValueError("chunk_overlap_tokens must be non-negative")
        if self.chunk_overlap_tokens >= self.chunk_target_tokens:
            raise ValueError("chunk_overlap_tokens must be smaller than chunk_target_tokens")
        if self.context_max_tokens <= 0:
            raise ValueError("context_max_tokens must be positive")
        return self

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

# Instantiate after imports so env vars are already in os.environ
settings = Settings()