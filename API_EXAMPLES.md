# API Examples (copy-paste into Postman)

Base URL (local): `http://127.0.0.1:8000`

## 1. Create an organization (onboarding — no auth)

`POST /api/v1/organizations`

```bash
curl -X POST http://127.0.0.1:8000/api/v1/organizations \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Acme Dental",
    "email": "ops@acmedental.com",
    "telephonyProvider": "twilio",
    "telephonyCredentials": {
      "accountSid": "ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
      "authToken": "your_twilio_auth_token",
      "fromNumber": "+14155550123"
    },
    "aiProvider": "azure_openai",
    "aiCredentials": {
      "endpoint": "https://your-resource.cognitiveservices.azure.com",
      "apiKey": "your_azure_openai_key",
      "deployment": "gpt-4.1",
      "apiVersion": "2025-01-01-preview"
    }
  }'
```

Response `201`:
```json
{
  "id": "b1f0c6d2-...",
  "name": "Acme Dental",
  "email": "ops@acmedental.com",
  "status": "active",
  "telephonyProvider": "twilio",
  "aiProvider": "azure_openai",
  "createdAt": "2026-07-02T10:00:00Z",
  "apiKey": "cak_9f1c...   <-- shown once, save it"
}
```

## 2. List organizations

```bash
curl http://127.0.0.1:8000/api/v1/organizations
```

## 3. Get one organization

```bash
curl http://127.0.0.1:8000/api/v1/organizations/{organizationId}
```

## 4. Rotate an organization's API key

```bash
curl -X POST http://127.0.0.1:8000/api/v1/organizations/{organizationId}/rotate-key
```

---

Everything below requires the `X-API-Key` header returned from step 1.

## 5. Create a call

`POST /api/v1/calls`

```bash
curl -X POST http://127.0.0.1:8000/api/v1/calls \
  -H "Content-Type: application/json" \
  -H "X-API-Key: cak_9f1c..." \
  -H "Idempotency-Key: appt-8823-attempt-1" \
  -d '{
    "toNumber": "+15551234567",
    "maxConversationDurationMinutes": 10,
    "callScript": {
      "persona": "You are Ava, a scheduling assistant for Acme Dental.",
      "objective": "Confirm the patient upcoming appointment and reschedule if needed.",
      "consentLine": "This call may be recorded and is conducted by an AI assistant. Do you consent to continue?",
      "fields": [
        {"name": "confirmed", "type": "boolean", "description": "Whether the patient confirms the appointment"},
        {"name": "newDate", "type": "string", "description": "Requested new date, if rescheduling"}
      ],
      "closingLine": "Thanks for your time, have a great day!"
    },
    "webhookUrl": "https://acmedental.example.com/webhooks/call-agent",
    "metadata": {"externalRef": "appt-8823"}
  }'
```

Response `202`:
```json
{
  "id": "9c2a1e4f-...",
  "status": "QUEUED",
  "toNumber": "+15551234567",
  "fromNumber": "+14155550123",
  "maxConversationDurationMinutes": 10,
  "extractedFields": {},
  "consentStatus": null,
  "endReason": null,
  "createdAt": "2026-07-02T10:05:00Z",
  "connectedAt": null,
  "endedAt": null
}
```

## 6. Get call status

```bash
curl http://127.0.0.1:8000/api/v1/calls/{callId} \
  -H "X-API-Key: cak_9f1c..."
```

## 7. List calls

```bash
curl "http://127.0.0.1:8000/api/v1/calls?limit=20" \
  -H "X-API-Key: cak_9f1c..."
```

## 8. Get call events (full lifecycle log)

```bash
curl http://127.0.0.1:8000/api/v1/calls/{callId}/events \
  -H "X-API-Key: cak_9f1c..."
```

Response:
```json
[
  {"id": "...", "eventType": "CALL_CREATED", "payload": {"toNumber": "+15551234567"}, "createdAt": "..."},
  {"id": "...", "eventType": "CALL_QUEUED", "payload": {}, "createdAt": "..."},
  {"id": "...", "eventType": "CALL_DIALING", "payload": {"providerCallSid": "CAxxxx"}, "createdAt": "..."},
  {"id": "...", "eventType": "CALL_CONNECTED", "payload": {}, "createdAt": "..."},
  {"id": "...", "eventType": "CONSENT_REQUESTED", "payload": {}, "createdAt": "..."},
  {"id": "...", "eventType": "CONSENT_GRANTED", "payload": {}, "createdAt": "..."},
  {"id": "...", "eventType": "TIME_WARNING", "payload": {"warning": "2min"}, "createdAt": "..."},
  {"id": "...", "eventType": "CALL_OBJECTIVE_COMPLETE", "payload": {}, "createdAt": "..."},
  {"id": "...", "eventType": "SUMMARY_GENERATED", "payload": {"summaryText": "..."}, "createdAt": "..."},
  {"id": "...", "eventType": "CALL_COMPLETED", "payload": {"endReason": "OBJECTIVE_COMPLETE"}, "createdAt": "..."}
]
```

## 9. Get conversation transcript

```bash
curl http://127.0.0.1:8000/api/v1/calls/{callId}/conversation \
  -H "X-API-Key: cak_9f1c..."
```

## 10. Get summary

```bash
curl http://127.0.0.1:8000/api/v1/calls/{callId}/summary \
  -H "X-API-Key: cak_9f1c..."
```

## 11. Cancel a call

```bash
curl -X POST http://127.0.0.1:8000/api/v1/calls/{callId}/cancel \
  -H "Content-Type: application/json" \
  -H "X-API-Key: cak_9f1c..." \
  -d '{"graceful": true}'
```

---

## Webhooks (called by Twilio, not by you)

- `POST /webhooks/twilio/voice/{callId}` — drives the entire in-call turn loop (consent → conversation → wrap-up).
- `POST /webhooks/twilio/status/{callId}` — call status changes (ringing/busy/no-answer/failed/completed).

Both verify Twilio's `X-Twilio-Signature` using the organization's stored auth token — Twilio must be able to reach `BASE_URL` (use a tunnel like `cloudflared`/`ngrok` for local dev, matching the existing `BASE_URL` in `.env`).
