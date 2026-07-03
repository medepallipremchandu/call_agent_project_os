from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.db.models import Organization
from app.schemas.calls import (
    CallCreateRequest,
    CallEventResponse,
    CallListResponse,
    CallResponse,
    CallSummaryResponse,
    CancelCallRequest,
    ConversationTurnResponse,
)
from app.core.security import get_current_organization
from app.services import calls as calls_service

router = APIRouter(prefix="/api/v1/calls", tags=["calls"])


def _to_call_response(call) -> CallResponse:
    return CallResponse(
        id=call.id,
        status=call.status,
        toNumber=call.to_number,
        fromNumber=call.from_number,
        maxConversationDurationMinutes=call.max_duration_minutes,
        extractedFields=call.extracted_fields,
        consentStatus=call.consent_status,
        endReason=call.end_reason,
        createdAt=call.created_at,
        connectedAt=call.connected_at,
        endedAt=call.ended_at,
    )


@router.post("", response_model=CallResponse, status_code=202)
async def create_call(
    payload: CallCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_db),
):
    call = await calls_service.create_call(db, organization, payload, idempotency_key)
    return _to_call_response(call)


@router.get("", response_model=CallListResponse)
async def list_calls(
    limit: int = 50,
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_db),
):
    calls = await calls_service.list_calls(db, organization, limit)
    return CallListResponse(items=[_to_call_response(c) for c in calls])


@router.get("/{call_id}", response_model=CallResponse)
async def get_call(
    call_id: uuid.UUID,
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_db),
):
    call = await calls_service.get_call(db, organization, call_id)
    return _to_call_response(call)


@router.get("/{call_id}/events", response_model=list[CallEventResponse])
async def get_call_events(
    call_id: uuid.UUID,
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_db),
):
    call = await calls_service.get_call(db, organization, call_id)
    events = await calls_service.get_events(db, call)
    return [
        CallEventResponse(id=e.id, eventType=e.event_type, payload=e.payload, createdAt=e.created_at) for e in events
    ]


@router.get("/{call_id}/conversation", response_model=list[ConversationTurnResponse])
async def get_call_conversation(
    call_id: uuid.UUID,
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_db),
):
    call = await calls_service.get_call(db, organization, call_id)
    turns = await calls_service.get_conversation(db, call)
    return [
        ConversationTurnResponse(turnIndex=t.turn_index, speaker=t.speaker, text=t.text, createdAt=t.created_at)
        for t in turns
    ]


@router.get("/{call_id}/summary", response_model=CallSummaryResponse | None)
async def get_call_summary(
    call_id: uuid.UUID,
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_db),
):
    call = await calls_service.get_call(db, organization, call_id)
    summary = await calls_service.get_summary(db, call)
    if summary is None:
        return None
    return CallSummaryResponse(
        summaryText=summary.summary_text, extractedFields=summary.extracted_fields, createdAt=summary.created_at
    )


@router.post("/{call_id}/cancel", response_model=CallResponse)
async def cancel_call(
    call_id: uuid.UUID,
    payload: CancelCallRequest,
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_db),
):
    call = await calls_service.get_call(db, organization, call_id)
    call = await calls_service.cancel_call(db, call, payload.graceful)
    return _to_call_response(call)
