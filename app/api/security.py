import secrets
from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader
from app.config import settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

def require_api_key(api_key: str | None = Security(api_key_header)) -> None:
    """
    FastAPI dependency that validates the X-API-Key header.
    - 503 if the server-side key is not configured (fail closed).
    - 401 if the client key is missing or does not match.
    """
    expected = settings.api_key
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="API authentication is not configured",
        )
    if not api_key or not secrets.compare_digest(api_key, expected):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key",
        )