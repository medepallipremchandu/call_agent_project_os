from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.organizations import (
    ApiKeyRotateResponse,
    OrganizationCreateRequest,
    OrganizationCreateResponse,
    OrganizationResponse,
)
from app.services import organizations as org_service

# NOTE: intentionally unauthenticated for now, per product decision — this is
# the onboarding surface that *issues* API keys, so it precedes API-key auth.
# Before exposing this publicly, put an operator-auth gate in front of it
# (see Phase 11 security notes) — anyone who can reach this endpoint can
# currently mint an org + API key.
router = APIRouter(prefix="/api/v1/organizations", tags=["organizations"])


@router.post("", response_model=OrganizationCreateResponse, status_code=201)
async def create_organization(payload: OrganizationCreateRequest, db: AsyncSession = Depends(get_db)):
    organization, plaintext_key = await org_service.create_organization(db, payload)
    fields = org_service.to_response_fields(organization, payload.telephonyProvider, payload.aiProvider)
    return OrganizationCreateResponse(**fields, apiKey=plaintext_key)


@router.get("", response_model=list[OrganizationResponse])
async def list_organizations(db: AsyncSession = Depends(get_db)):
    orgs = await org_service.list_organizations(db)
    responses = []
    for org in orgs:
        telephony = await org_service.get_credential(db, org.id, "telephony")
        ai = await org_service.get_credential(db, org.id, "ai")
        responses.append(OrganizationResponse(**org_service.to_response_fields(org, telephony.provider, ai.provider)))
    return responses


@router.get("/{organization_id}", response_model=OrganizationResponse)
async def get_organization(organization_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    org = await org_service.get_organization(db, organization_id)
    telephony = await org_service.get_credential(db, org.id, "telephony")
    ai = await org_service.get_credential(db, org.id, "ai")
    return OrganizationResponse(**org_service.to_response_fields(org, telephony.provider, ai.provider))


@router.post("/{organization_id}/rotate-key", response_model=ApiKeyRotateResponse)
async def rotate_key(organization_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    await org_service.get_organization(db, organization_id)  # 404 if missing
    plaintext_key = await org_service.rotate_api_key(db, organization_id)
    return ApiKeyRotateResponse(apiKey=plaintext_key)
