from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Absolute path so settings load correctly regardless of the current working
# directory (e.g. running `python main.py` from inside app/, or `python
# app/main.py` from the project root, or `uvicorn app.main:app` from anywhere).
_ENV_FILE = Path(__file__).resolve().parent.parent.parent / ".env"


class Settings(BaseSettings):
    """Infra-level settings only. Per-tenant telephony/AI credentials live in
    the database (encrypted), not here — see app/db/models.py ProviderCredential.
    """

    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore")

    database_url: str

    # Public base URL this service is reachable at, used to build Twilio
    # webhook callback URLs (voice/gather/status).
    base_url: str

    # Fernet key used to encrypt provider credentials at rest.
    # Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    credential_encryption_key: str

    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
