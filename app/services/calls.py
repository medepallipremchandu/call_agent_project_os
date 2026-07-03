from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.crypto import decrypt_credentials
from app.core.state_machine import CallStatus, validate_transition
from app.db.models import Call, CallEvent, CallSummary, ConversationTurn, IdempotencyKey, Organization
from app.providers.telephony import get_telephony_provider
from app.schemas.calls import CallCreateRequest
from app.services.organizations import get_credential


async def log_event(db: AsyncSession, call: Call, event_type: str, payload: dict | None = None) -> CallEvent:
    event = CallEvent(call_id=call.id, event_type=event_type, payload=payload or {})
    db.add(event)
    await db.flush()
    return event


async def transition(db: AsyncSession, call: Call, target: CallStatus, event_type: str, payload: dict | None = None) -> None:
    validate_transition(CallStatus(call.status), target)
    call.status = target.value
    if target == CallStatus.CONNECTED:
        call.connected_at = datetime.now(timezone.utc)
    if target in {
        CallStatus.COMPLETED,
        CallStatus.FAILED,
        CallStatus.BUSY,
        CallStatus.NO_ANSWER,
        CallStatus.DISCONNECTED,
        CallStatus.TIMEOUT,
        CallStatus.CANCELLED,
        CallStatus.CALL_BLOCKED,
        CallStatus.CONSENT_DENIED,
    }:
        call.ended_at = datetime.now(timezone.utc)
    await log_event(db, call, event_type, payload)
    await db.flush()


async def create_call(db: AsyncSession, organization: Organization, payload: CallCreateRequest, idempotency_key: str | None) -> Call:
    if idempotency_key:
        existing = await db.execute(
            select(IdempotencyKey).where(
                IdempotencyKey.organization_id == organization.id, IdempotencyKey.key == idempotency_key
            )
        )
        row = existing.scalar_one_or_none()
        if row is not None:
            result = await db.execute(select(Call).where(Call.id == row.call_id))
            return result.scalar_one()

    telephony_credential = await get_credential(db, organization.id, "telephony")
    telephony_creds = decrypt_credentials(telephony_credential.encrypted_payload)

    call = Call(
        organization_id=organization.id,
        to_number=payload.toNumber,
        from_number=telephony_creds["fromNumber"],
        status=CallStatus.CREATED.value,
        max_duration_minutes=payload.maxConversationDurationMinutes,
        call_script=payload.callScript.model_dump(),
        webhook_url=payload.webhookUrl,
        metadata_json=payload.metadata,
    )
    db.add(call)
    await db.flush()
    await log_event(db, call, "CALL_CREATED", {"toNumber": payload.toNumber})

    if idempotency_key:
        db.add(IdempotencyKey(organization_id=organization.id, key=idempotency_key, call_id=call.id))

    await transition(db, call, CallStatus.QUEUED, "CALL_QUEUED")
    await db.commit()

    try:
        provider = get_telephony_provider(telephony_credential.provider, telephony_creds)
        settings = get_settings()
        provider_call_sid = await provider.place_call(
            to_number=call.to_number, from_number=call.from_number, call_id=call.id, base_url=settings.base_url
        )
        call.provider_call_sid = provider_call_sid
        await transition(db, call, CallStatus.DIALING, "CALL_DIALING", {"providerCallSid": provider_call_sid})
    except Exception as exc:  # provider/network failure placing the call
        await transition(db, call, CallStatus.FAILED, "CALL_FAILED", {"reason": str(exc)})
        call.end_reason = "PROVIDER_ERROR"

    await db.commit()
    await db.refresh(call)
    return call


async def get_call(db: AsyncSession, organization: Organization, call_id: uuid.UUID) -> Call:
    result = await db.execute(select(Call).where(Call.id == call_id, Call.organization_id == organization.id))
    call = result.scalar_one_or_none()
    if call is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Call not found")
    return call


async def list_calls(db: AsyncSession, organization: Organization, limit: int = 50) -> list[Call]:
    result = await db.execute(
        select(Call).where(Call.organization_id == organization.id).order_by(Call.created_at.desc()).limit(limit)
    )
    return list(result.scalars().all())


async def get_events(db: AsyncSession, call: Call) -> list[CallEvent]:
    result = await db.execute(select(CallEvent).where(CallEvent.call_id == call.id).order_by(CallEvent.created_at))
    return list(result.scalars().all())


async def get_conversation(db: AsyncSession, call: Call) -> list[ConversationTurn]:
    result = await db.execute(
        select(ConversationTurn).where(ConversationTurn.call_id == call.id).order_by(ConversationTurn.turn_index)
    )
    return list(result.scalars().all())


async def get_summary(db: AsyncSession, call: Call) -> CallSummary | None:
    result = await db.execute(select(CallSummary).where(CallSummary.call_id == call.id))
    return result.scalar_one_or_none()


async def cancel_call(db: AsyncSession, call: Call, graceful: bool) -> Call:
    if CallStatus(call.status) in {
        CallStatus.COMPLETED,
        CallStatus.FAILED,
        CallStatus.BUSY,
        CallStatus.NO_ANSWER,
        CallStatus.DISCONNECTED,
        CallStatus.TIMEOUT,
        CallStatus.CANCELLED,
        CallStatus.CALL_BLOCKED,
        CallStatus.CONSENT_DENIED,
    }:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"Call already in terminal state {call.status}")

    await transition(db, call, CallStatus.CANCELLED, "CALL_CANCELLED", {"graceful": graceful})
    call.end_reason = "CANCELLED_BY_TENANT"
    await db.commit()
    await db.refresh(call)
    return call
