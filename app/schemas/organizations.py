from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field

TelephonyProviderName = Literal["twilio"]
AiProviderName = Literal["azure_openai", "openai"]


class TwilioCredentials(BaseModel):
    accountSid: str = Field(min_length=1)
    authToken: str = Field(min_length=1)
    fromNumber: str = Field(min_length=1, description="E.164 phone number, e.g. +14155550123")


class AzureOpenAiCredentials(BaseModel):
    endpoint: str = Field(min_length=1)
    apiKey: str = Field(min_length=1)
    deployment: str = Field(min_length=1)
    apiVersion: str = Field(default="2025-01-01-preview")


class OpenAiCredentials(BaseModel):
    apiKey: str = Field(min_length=1)
    model: str = Field(default="gpt-4o-mini")


class OrganizationCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    email: EmailStr

    telephonyProvider: TelephonyProviderName
    telephonyCredentials: TwilioCredentials

    aiProvider: AiProviderName
    aiCredentials: AzureOpenAiCredentials | OpenAiCredentials

    def credentials_for(self, provider: AiProviderName) -> AzureOpenAiCredentials | OpenAiCredentials:
        return self.aiCredentials


class OrganizationResponse(BaseModel):
    id: uuid.UUID
    name: str
    email: str
    status: str
    telephonyProvider: str
    aiProvider: str
    createdAt: datetime


class OrganizationCreateResponse(OrganizationResponse):
    apiKey: str = Field(description="Shown once. Store it now — it cannot be retrieved again.")


class ApiKeyRotateResponse(BaseModel):
    apiKey: str = Field(description="Shown once. The previous key is now revoked.")
