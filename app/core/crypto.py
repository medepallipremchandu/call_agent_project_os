from __future__ import annotations

import json

from cryptography.fernet import Fernet

from app.core.config import get_settings


def _fernet() -> Fernet:
    return Fernet(get_settings().credential_encryption_key.encode())


def encrypt_credentials(payload: dict) -> str:
    raw = json.dumps(payload).encode()
    return _fernet().encrypt(raw).decode()


def decrypt_credentials(encrypted_payload: str) -> dict:
    raw = _fernet().decrypt(encrypted_payload.encode())
    return json.loads(raw)
