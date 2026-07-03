from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class CallScriptField(BaseModel):
    name: str = Field(min_length=1, description="Key the extracted value will be stored under")
    type: Literal["string", "boolean", "number", "date"] = "string"
    description: str = Field(min_length=1, description="What the AI should try to capture, in plain English")


class CallScript(BaseModel):
    persona: str = Field(min_length=1, description="Who the AI is, e.g. 'You are Ava, a scheduling assistant for Acme Dental.'")
    objective: str = Field(min_length=1, description="What the call is trying to accomplish")
    consentLine: str = Field(
        default="This call may be recorded and is conducted by an AI assistant. Do you consent to continue?",
        description="Spoken verbatim before any data collection begins",
    )
    fields: list[CallScriptField] = Field(default_factory=list, description="Structured data to extract during the call")
    closingLine: str = Field(default="Thanks for your time, have a great day!")


class CallCreateRequest(BaseModel):
    toNumber: str = Field(min_length=1, description="E.164 phone number to dial, e.g. +14155550123")
    maxConversationDurationMinutes: int = Field(ge=1, le=60)
    callScript: CallScript
    webhookUrl: str | None = Field(default=None, description="Tenant endpoint notified on every event")
    metadata: dict[str, Any] = Field(default_factory=dict)


class CallResponse(BaseModel):
    id: uuid.UUID
    status: str
    toNumber: str
    fromNumber: str
    maxConversationDurationMinutes: int
    extractedFields: dict[str, Any]
    consentStatus: str | None
    endReason: str | None
    createdAt: datetime
    connectedAt: datetime | None
    endedAt: datetime | None


class CallEventResponse(BaseModel):
    id: uuid.UUID
    eventType: str
    payload: dict[str, Any]
    createdAt: datetime


class ConversationTurnResponse(BaseModel):
    turnIndex: int
    speaker: str
    text: str
    createdAt: datetime


class CallSummaryResponse(BaseModel):
    summaryText: str
    extractedFields: dict[str, Any]
    createdAt: datetime


class CallListResponse(BaseModel):
    items: list[CallResponse]
    nextCursor: str | None = None


class CancelCallRequest(BaseModel):
    graceful: bool = Field(default=True, description="If true, AI wraps up politely before hanging up")
