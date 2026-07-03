from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import encrypt_credentials
from app.core.security import generate_api_key
from app.db.models import ApiKey, Organization, ProviderCredential
from app.schemas.organizations import OrganizationCreateRequest


async def create_organization(db: AsyncSession, payload: OrganizationCreateRequest) -> tuple[Organization, str]:
    organization = Organization(name=payload.name, email=payload.email)
    db.add(organization)
    await db.flush()  # assigns organization.id

    telephony_credential = ProviderCredential(
        organization_id=organization.id,
        credential_type="telephony",
        provider=payload.telephonyProvider,
        encrypted_payload=encrypt_credentials(payload.telephonyCredentials.model_dump()),
    )
    ai_credential = ProviderCredential(
        organization_id=organization.id,
        credential_type="ai",
        provider=payload.aiProvider,
        encrypted_payload=encrypt_credentials(payload.aiCredentials.model_dump()),
    )
    db.add_all([telephony_credential, ai_credential])

    plaintext_key, key_prefix, key_hash = generate_api_key()
    api_key = ApiKey(organization_id=organization.id, key_hash=key_hash, key_prefix=key_prefix)
    db.add(api_key)

    await db.commit()
    await db.refresh(organization)
    return organization, plaintext_key


async def list_organizations(db: AsyncSession) -> list[Organization]:
    result = await db.execute(select(Organization).order_by(Organization.created_at.desc()))
    return list(result.scalars().all())


async def get_organization(db: AsyncSession, organization_id: uuid.UUID) -> Organization:
    result = await db.execute(select(Organization).where(Organization.id == organization_id))
    organization = result.scalar_one_or_none()
    if organization is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Organization not found")
    return organization


async def get_credential(db: AsyncSession, organization_id: uuid.UUID, credential_type: str) -> ProviderCredential:
    result = await db.execute(
        select(ProviderCredential).where(
            ProviderCredential.organization_id == organization_id,
            ProviderCredential.credential_type == credential_type,
        )
    )
    credential = result.scalar_one_or_none()
    if credential is None:
        raise HTTPException(
            status.HTTP_412_PRECONDITION_FAILED,
            detail=f"Organization has no '{credential_type}' credentials configured",
        )
    return credential


async def rotate_api_key(db: AsyncSession, organization_id: uuid.UUID) -> str:
    result = await db.execute(
        select(ApiKey).where(ApiKey.organization_id == organization_id, ApiKey.revoked_at.is_(None))
    )
    for existing in result.scalars().all():
        existing.revoked_at = _now()

    plaintext_key, key_prefix, key_hash = generate_api_key()
    db.add(ApiKey(organization_id=organization_id, key_hash=key_hash, key_prefix=key_prefix))
    await db.commit()
    return plaintext_key


def _now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


def to_response_fields(organization: Organization, telephony_provider: str, ai_provider: str) -> dict:
    return {
        "id": organization.id,
        "name": organization.name,
        "email": organization.email,
        "status": organization.status,
        "telephonyProvider": telephony_provider,
        "aiProvider": ai_provider,
        "createdAt": organization.created_at,
    }
