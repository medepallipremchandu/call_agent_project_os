from __future__ import annotations

import hashlib
import secrets
import uuid

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.db.models import ApiKey, Organization

API_KEY_PREFIX = "cak_"  # call-agent-key


def generate_api_key() -> tuple[str, str, str]:
    """Returns (plaintext_key, key_prefix, key_hash). Plaintext is shown to the
    caller exactly once and never stored.
    """
    plaintext = f"{API_KEY_PREFIX}{secrets.token_urlsafe(32)}"
    key_prefix = plaintext[: len(API_KEY_PREFIX) + 8]
    key_hash = hash_api_key(plaintext)
    return plaintext, key_prefix, key_hash


def hash_api_key(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode()).hexdigest()


async def get_current_organization(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    db: AsyncSession = Depends(get_db),
) -> Organization:
    if not x_api_key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Missing X-API-Key header")

    key_hash = hash_api_key(x_api_key)
    result = await db.execute(select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.revoked_at.is_(None)))
    api_key = result.scalar_one_or_none()
    if api_key is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid or revoked API key")

    result = await db.execute(select(Organization).where(Organization.id == api_key.organization_id))
    organization = result.scalar_one_or_none()
    if organization is None or organization.status != "active":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Organization is not active")

    return organization


async def require_org_call(call_id: uuid.UUID, organization: Organization, db: AsyncSession):
    from app.db.models import Call  # local import to avoid circular import at module load

    result = await db.execute(select(Call).where(Call.id == call_id, Call.organization_id == organization.id))
    call = result.scalar_one_or_none()
    if call is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Call not found")
    return call
