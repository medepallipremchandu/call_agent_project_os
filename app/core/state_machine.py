from __future__ import annotations

from enum import StrEnum


class CallStatus(StrEnum):
    CREATED = "CREATED"
    QUEUED = "QUEUED"
    DIALING = "DIALING"
    RINGING = "RINGING"
    CONNECTED = "CONNECTED"
    CONSENT_PENDING = "CONSENT_PENDING"
    CONSENT_DENIED = "CONSENT_DENIED"
    CONVERSATION = "CONVERSATION"
    SUMMARY = "SUMMARY"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    BUSY = "BUSY"
    NO_ANSWER = "NO_ANSWER"
    DISCONNECTED = "DISCONNECTED"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"
    CALL_BLOCKED = "CALL_BLOCKED"


TERMINAL_STATES = {
    CallStatus.CONSENT_DENIED,
    CallStatus.COMPLETED,
    CallStatus.FAILED,
    CallStatus.BUSY,
    CallStatus.NO_ANSWER,
    CallStatus.DISCONNECTED,
    CallStatus.TIMEOUT,
    CallStatus.CANCELLED,
    CallStatus.CALL_BLOCKED,
}

# Explicit adjacency list. Anything not listed here as a valid destination is
# rejected by `transition()` — this is what makes the lifecycle deterministic.
ALLOWED_TRANSITIONS: dict[CallStatus, set[CallStatus]] = {
    CallStatus.CREATED: {CallStatus.QUEUED, CallStatus.CALL_BLOCKED, CallStatus.CANCELLED},
    CallStatus.QUEUED: {CallStatus.DIALING, CallStatus.FAILED, CallStatus.CANCELLED},
    CallStatus.DIALING: {CallStatus.RINGING, CallStatus.BUSY, CallStatus.NO_ANSWER, CallStatus.FAILED, CallStatus.CANCELLED},
    CallStatus.RINGING: {CallStatus.CONNECTED, CallStatus.NO_ANSWER, CallStatus.BUSY, CallStatus.FAILED, CallStatus.CANCELLED},
    CallStatus.CONNECTED: {CallStatus.CONSENT_PENDING, CallStatus.DISCONNECTED, CallStatus.FAILED, CallStatus.CANCELLED},
    CallStatus.CONSENT_PENDING: {
        CallStatus.CONVERSATION,
        CallStatus.CONSENT_DENIED,
        CallStatus.DISCONNECTED,
        CallStatus.TIMEOUT,
        CallStatus.CANCELLED,
    },
    CallStatus.CONVERSATION: {
        CallStatus.SUMMARY,
        CallStatus.DISCONNECTED,
        CallStatus.TIMEOUT,
        CallStatus.FAILED,
        CallStatus.CANCELLED,
    },
    CallStatus.SUMMARY: {CallStatus.COMPLETED, CallStatus.FAILED},
}


class InvalidTransitionError(Exception):
    pass


def validate_transition(current: CallStatus, target: CallStatus) -> None:
    if current in TERMINAL_STATES:
        raise InvalidTransitionError(f"Call is in terminal state {current}, cannot transition to {target}")
    allowed = ALLOWED_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise InvalidTransitionError(f"Illegal transition {current} -> {target}")
