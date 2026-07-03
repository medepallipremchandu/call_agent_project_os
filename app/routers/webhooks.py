from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from twilio.request_validator import RequestValidator
from twilio.twiml.voice_response import Gather, VoiceResponse

from app.core.config import get_settings
from app.core.crypto import decrypt_credentials
from app.core.state_machine import CallStatus
from app.db.models import Call, ConversationTurn
from app.db.session import get_db
from app.providers.ai import get_ai_provider
from app.schemas.calls import CallScript
from app.services import calls as calls_service
from app.services.conversation import ConversationService
from app.services.organizations import get_credential

router = APIRouter(prefix="/webhooks/twilio", tags=["webhooks"])

MAX_SILENCE_RETRIES = 2
MAX_CONSENT_RETRIES = 3
WARNING_2MIN_SECONDS = 120
WARNING_1MIN_SECONDS = 60


async def _load_call_or_404(db: AsyncSession, call_id: uuid.UUID) -> Call:
    result = await db.execute(select(Call).where(Call.id == call_id))
    call = result.scalar_one_or_none()
    if call is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Unknown call")
    return call


async def _verify_twilio_signature(request: Request, db: AsyncSession, call: Call) -> None:
    telephony_credential = await get_credential(db, call.organization_id, "telephony")
    creds = decrypt_credentials(telephony_credential.encrypted_payload)
    validator = RequestValidator(creds["authToken"])

    form = await request.form()
    signature = request.headers.get("X-Twilio-Signature", "")
    settings = get_settings()
    url = f"{settings.base_url}{request.url.path}"

    if not validator.validate(url, dict(form), signature):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Invalid Twilio signature")


async def _conversation_service_for(db: AsyncSession, call: Call) -> ConversationService:
    ai_credential = await get_credential(db, call.organization_id, "ai")
    creds = decrypt_credentials(ai_credential.encrypted_payload)
    return ConversationService(get_ai_provider(ai_credential.provider, creds))


async def _append_turn(db: AsyncSession, call: Call, speaker: str, text: str) -> None:
    result = await db.execute(select(ConversationTurn.turn_index).where(ConversationTurn.call_id == call.id))
    existing = list(result.scalars().all())
    next_index = max(existing, default=-1) + 1
    db.add(ConversationTurn(call_id=call.id, turn_index=next_index, speaker=speaker, text=text))
    await db.flush()


async def _history(db: AsyncSession, call: Call) -> list[dict]:
    result = await db.execute(
        select(ConversationTurn).where(ConversationTurn.call_id == call.id).order_by(ConversationTurn.turn_index)
    )
    return [{"speaker": t.speaker, "text": t.text} for t in result.scalars().all()]


def _bump_metadata_counter(call: Call, key: str) -> int:
    metadata = dict(call.metadata_json or {})
    value = int(metadata.get(key, 0)) + 1
    metadata[key] = value
    call.metadata_json = metadata
    return value


def _reset_metadata_counter(call: Call, key: str) -> None:
    metadata = dict(call.metadata_json or {})
    metadata[key] = 0
    call.metadata_json = metadata


def _say_and_gather(action_url: str, say_text: str) -> str:
    vr = VoiceResponse()
    vr.say(say_text)
    gather = Gather(input="speech", action=action_url, method="POST", speech_timeout="auto", timeout=6)
    vr.append(gather)
    vr.redirect(action_url, method="POST")
    return str(vr)


def _say_and_hangup(say_text: str) -> str:
    vr = VoiceResponse()
    vr.say(say_text)
    vr.hangup()
    return str(vr)


async def _finish_with_summary(db: AsyncSession, call: Call, conversation: ConversationService, script: CallScript, end_reason: str) -> str:
    history = await _history(db, call)
    try:
        result = await conversation.generate_summary(script=script, history=history, extracted_fields=call.extracted_fields)
        summary_text = result.get("summary_text", "")
        final_fields = result.get("extracted_fields", call.extracted_fields)
    except Exception:
        summary_text = "Summary unavailable — AI summarization failed after call completion."
        final_fields = call.extracted_fields

    from app.db.models import CallSummary

    db.add(CallSummary(call_id=call.id, summary_text=summary_text, extracted_fields=final_fields))
    call.extracted_fields = final_fields
    await calls_service.log_event(db, call, "SUMMARY_GENERATED", {"summaryText": summary_text})
    await calls_service.transition(db, call, CallStatus.COMPLETED, "CALL_COMPLETED", {"endReason": end_reason})
    call.end_reason = end_reason
    return _say_and_hangup(script.closingLine)


@router.post("/voice/{call_id}")
async def voice_and_gather(call_id: uuid.UUID, request: Request, db: AsyncSession = Depends(get_db)):
    """Single endpoint for the entire in-call turn loop.

    Twilio hits this once on answer (no SpeechResult) and again after every
    <Gather> — either with a SpeechResult, or via the trailing <Redirect> when
    the callee stayed silent. Branching on `call.status` tells us which stage
    of the conversation we're in; there is no separate in-memory session.
    """
    call = await _load_call_or_404(db, call_id)
    await _verify_twilio_signature(request, db, call)

    form = await request.form()
    speech_result = (form.get("SpeechResult") or "").strip()
    action_url = f"{get_settings().base_url}/webhooks/twilio/voice/{call_id}"
    script = CallScript.model_validate(call.call_script)
    conversation = await _conversation_service_for(db, call)

    # First hit for this call: mark connected and open with the consent ask.
    if CallStatus(call.status) in {CallStatus.DIALING, CallStatus.RINGING}:
        await calls_service.transition(db, call, CallStatus.CONNECTED, "CALL_CONNECTED")
        await calls_service.transition(db, call, CallStatus.CONSENT_PENDING, "CONSENT_REQUESTED")
        await _append_turn(db, call, "ai", script.consentLine)
        await db.commit()
        return Response(content=_say_and_gather(action_url, script.consentLine), media_type="application/xml")

    if not speech_result:
        silence_count = _bump_metadata_counter(call, "silence_count")
        if silence_count > MAX_SILENCE_RETRIES:
            await calls_service.transition(db, call, CallStatus.DISCONNECTED, "CALL_DISCONNECTED", {"reason": "callee_unresponsive"})
            call.end_reason = "CALLEE_UNRESPONSIVE"
            await db.commit()
            return Response(content=_say_and_hangup("We haven't heard from you, goodbye."), media_type="application/xml")
        await db.commit()
        return Response(
            content=_say_and_gather(action_url, "Sorry, I didn't catch that. Could you say that again?"),
            media_type="application/xml",
        )
    _reset_metadata_counter(call, "silence_count")
    await _append_turn(db, call, "callee", speech_result)

    if CallStatus(call.status) == CallStatus.CONSENT_PENDING:
        result = await conversation.consent_turn(script=script, callee_speech=speech_result)
        consent = (result.get("consent") or "unclear").lower()

        if consent == "yes":
            call.consent_status = "granted"
            await calls_service.transition(db, call, CallStatus.CONVERSATION, "CONSENT_GRANTED")
            opening = await conversation.main_turn(script=script, history=await _history(db, call), callee_speech="")
            await _append_turn(db, call, "ai", opening.get("ai_response", ""))
            await db.commit()
            return Response(content=_say_and_gather(action_url, opening.get("ai_response", "")), media_type="application/xml")

        if consent == "no":
            call.consent_status = "denied"
            await calls_service.transition(db, call, CallStatus.CONSENT_DENIED, "CONSENT_DENIED")
            call.end_reason = "CONSENT_DENIED"
            await db.commit()
            return Response(content=_say_and_hangup(script.closingLine), media_type="application/xml")

        retries = _bump_metadata_counter(call, "consent_retry_count")
        if retries > MAX_CONSENT_RETRIES:
            call.consent_status = "denied"
            await calls_service.transition(db, call, CallStatus.CONSENT_DENIED, "CONSENT_DENIED", {"reason": "no_clear_response"})
            call.end_reason = "CONSENT_UNCLEAR_EXHAUSTED_RETRIES"
            await db.commit()
            return Response(content=_say_and_hangup(script.closingLine), media_type="application/xml")

        ai_response = result.get("ai_response") or "Sorry, I didn't quite catch that — do you consent to continue?"
        await _append_turn(db, call, "ai", ai_response)
        await db.commit()
        return Response(content=_say_and_gather(action_url, ai_response), media_type="application/xml")

    if CallStatus(call.status) == CallStatus.CONVERSATION:
        elapsed_seconds = (datetime.now(timezone.utc) - call.connected_at).total_seconds()
        remaining_seconds = call.max_duration_minutes * 60 - elapsed_seconds

        if remaining_seconds <= 0:
            await calls_service.transition(db, call, CallStatus.SUMMARY, "CALL_TIME_LIMIT_REACHED")
            twiml = await _finish_with_summary(db, call, conversation, script, end_reason="TIME_LIMIT_REACHED")
            await db.commit()
            return Response(content=twiml, media_type="application/xml")

        time_notice = None
        if remaining_seconds <= WARNING_1MIN_SECONDS and not call.warned_1min:
            call.warned_1min = True
            time_notice = "Just one more minute left, so let's wrap up shortly."
            await calls_service.log_event(db, call, "TIME_WARNING", {"remainingSeconds": remaining_seconds, "warning": "1min"})
        elif remaining_seconds <= WARNING_2MIN_SECONDS and not call.warned_2min:
            call.warned_2min = True
            time_notice = (
                "Just a quick note - we have about two minutes left in our conversation. "
                "I'll make sure we capture anything important before we wrap up."
            )
            await calls_service.log_event(db, call, "TIME_WARNING", {"remainingSeconds": remaining_seconds, "warning": "2min"})

        result = await conversation.main_turn(
            script=script, history=await _history(db, call), callee_speech=speech_result, time_notice=time_notice
        )
        new_fields = {k: v for k, v in (result.get("fields") or {}).items() if v}
        if new_fields:
            call.extracted_fields = {**call.extracted_fields, **new_fields}

        ai_response = result.get("ai_response", "")
        await _append_turn(db, call, "ai", ai_response)

        if result.get("done"):
            await calls_service.transition(db, call, CallStatus.SUMMARY, "CALL_OBJECTIVE_COMPLETE")
            twiml = await _finish_with_summary(db, call, conversation, script, end_reason="OBJECTIVE_COMPLETE")
            await db.commit()
            return Response(content=twiml, media_type="application/xml")

        await db.commit()
        return Response(content=_say_and_gather(action_url, ai_response), media_type="application/xml")

    # Call already in a terminal or otherwise unexpected state — end gracefully.
    await db.commit()
    return Response(content=_say_and_hangup(script.closingLine), media_type="application/xml")


@router.post("/status/{call_id}")
async def call_status(call_id: uuid.UUID, request: Request, db: AsyncSession = Depends(get_db)):
    call = await _load_call_or_404(db, call_id)
    await _verify_twilio_signature(request, db, call)

    form = await request.form()
    twilio_status = (form.get("CallStatus") or "").lower()

    transition_map = {
        "ringing": (CallStatus.RINGING, "CALL_RINGING"),
        "busy": (CallStatus.BUSY, "CALL_BUSY"),
        "no-answer": (CallStatus.NO_ANSWER, "CALL_NO_ANSWER"),
        "failed": (CallStatus.FAILED, "CALL_FAILED"),
        "canceled": (CallStatus.CANCELLED, "CALL_CANCELLED"),
        "completed": (CallStatus.DISCONNECTED, "CALL_DISCONNECTED"),
    }
    target = transition_map.get(twilio_status)
    if target is not None and CallStatus(call.status) not in {
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
        try:
            await calls_service.transition(db, call, target[0], target[1], {"providerStatus": twilio_status})
            if target[0] != CallStatus.RINGING:
                call.end_reason = call.end_reason or target[0].value
        except Exception:
            # Duplicate/out-of-order provider webhook racing our own turn logic —
            # already-terminal or not-yet-reachable target is a no-op, not an error.
            await calls_service.log_event(db, call, "PROVIDER_STATUS_IGNORED", {"providerStatus": twilio_status})
    else:
        await calls_service.log_event(db, call, "PROVIDER_STATUS_RECEIVED", {"providerStatus": twilio_status})

    await db.commit()
    return Response(status_code=204)
