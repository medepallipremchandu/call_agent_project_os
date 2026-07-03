from __future__ import annotations

import asyncio
import uuid
from abc import ABC, abstractmethod

from twilio.rest import Client as TwilioClient


class TelephonyProvider(ABC):
    """Adapter interface. Add a new provider by implementing this and
    registering it in `get_telephony_provider` below — no changes needed to
    call orchestration logic.
    """

    @abstractmethod
    async def place_call(self, *, to_number: str, from_number: str, call_id: uuid.UUID, base_url: str) -> str:
        """Place an outbound call. Returns the provider's call SID/ID."""

    @abstractmethod
    async def fetch_recording_url(self, provider_call_sid: str) -> str | None:
        """Best-effort lookup of a call recording URL, if any."""


class TwilioTelephonyProvider(TelephonyProvider):
    def __init__(self, *, account_sid: str, auth_token: str, from_number: str) -> None:
        self._client = TwilioClient(account_sid, auth_token)
        self._account_sid = account_sid
        self._auth_token = auth_token
        self.from_number = from_number

    async def place_call(self, *, to_number: str, from_number: str, call_id: uuid.UUID, base_url: str) -> str:
        call = await asyncio.to_thread(
            self._client.calls.create,
            to=to_number,
            from_=from_number,
            url=f"{base_url}/webhooks/twilio/voice/{call_id}",
            status_callback=f"{base_url}/webhooks/twilio/status/{call_id}",
            status_callback_event=["initiated", "ringing", "answered", "completed"],
            status_callback_method="POST",
            record=True,
        )
        return call.sid

    async def fetch_recording_url(self, provider_call_sid: str) -> str | None:
        recordings = await asyncio.to_thread(self._client.recordings.list, call_sid=provider_call_sid, limit=1)
        if not recordings:
            return None
        rec = recordings[0]
        return f"https://api.twilio.com{rec.uri.replace('.json', '.mp3')}"


def get_telephony_provider(provider: str, credentials: dict) -> TelephonyProvider:
    if provider == "twilio":
        return TwilioTelephonyProvider(
            account_sid=credentials["accountSid"],
            auth_token=credentials["authToken"],
            from_number=credentials["fromNumber"],
        )
    raise ValueError(f"Unsupported telephony provider: {provider}")
