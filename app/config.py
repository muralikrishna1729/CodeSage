import os

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# Load .env into the *process environment* before Settings() runs. pydantic-settings
# only reads the file into the Settings object; libraries that read env vars directly
# (langsmith/langgraph tracing: LANGSMITH_TRACING, LANGSMITH_ENDPOINT, LANGCHAIN_API_KEY,
# LANGCHAIN_PROJECT) need the variables to actually exist in os.environ. Existing shell
# variables win over the file (dotenv's default).
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
    qdrant_https: bool = False # set true for Qdrant Cloud / TLS endpoints
    embed_model: str = "jinaai/jina-embeddings-v2-base-code"
    collection_name: str = "codebase_chunks"
    groq_model: str = "openai/gpt-oss-120b"
    groq_fast_model: str = "openai/gpt-oss-20b"
    openrouter_model: str = "meta-llama/llama-3.3-70b-instruct:free"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()