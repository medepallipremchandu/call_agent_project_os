from __future__ import annotations

import json

from app.providers.ai import AiProvider
from app.schemas.calls import CallScript

# Candidate/callee speech is always placed in a JSON *data* field, never
# interpolated into the instruction text, to mitigate prompt injection.


def _consent_system_prompt(script: CallScript) -> str:
    return f"""You are an AI voice agent. {script.persona}

You have just said to the callee: "{script.consentLine}"

Your ONLY job right now is to determine whether the callee consents to continue
(recording + being spoken with by an AI). Do NOT pursue the call objective yet.

The callee may not answer directly — they may ask a question or say something
unrelated. If so, give a brief, polite reply, then clearly re-ask for a yes or no.

Always respond in JSON with these exact keys:
{{
    "consent": "<yes, no, or unclear>",
    "ai_response": "<what to say next; used only when consent is 'unclear', otherwise empty string>"
}}

Do NOT infer or report the callee's emotional state, mood, affect, or sentiment.
"""


def _main_system_prompt(script: CallScript, time_notice: str | None) -> str:
    field_spec = json.dumps(
        {f.name: {"type": f.type, "description": f.description} for f in script.fields}, indent=2
    )
    notice_instruction = (
        f'Before your next reply, naturally work in this time notice, verbatim in spirit: "{time_notice}"'
        if time_notice
        else "No time notice needed for this turn."
    )
    return f"""You are an AI voice agent. {script.persona}

Objective: {script.objective}

You need to collect the following structured fields over the course of the
conversation (a JSON schema, not something to read aloud to the callee):
{field_spec}

{notice_instruction}

When the objective is complete or the callee wants to end the call, set
"done": true and use "{script.closingLine}" (or a natural variation of it) as
part of your closing ai_response.

Always respond in JSON with these exact keys:
{{
    "ai_response": "<your conversational reply to speak to the callee>",
    "fields": {{<one key per field above, current best-known value or empty string if not yet known>}},
    "done": <true or false>
}}

Do NOT infer or report the callee's emotional state, mood, affect, or sentiment.
"""


def _summary_system_prompt(script: CallScript) -> str:
    return f"""You are summarizing a completed AI voice call. {script.persona}
Objective was: {script.objective}

Given the full conversation transcript and the fields extracted, write a
concise, factual summary (3-5 sentences) for the business that requested this
call. Always respond in JSON with these exact keys:
{{
    "summary_text": "<concise natural-language summary>",
    "extracted_fields": {{<final best-known value for each requested field>}}
}}
"""


class ConversationService:
    def __init__(self, ai_provider: AiProvider) -> None:
        self._ai = ai_provider

    async def consent_turn(self, *, script: CallScript, callee_speech: str) -> dict:
        return await self._ai.complete_json(
            system_prompt=_consent_system_prompt(script),
            user_content=json.dumps({"callee_reply": callee_speech}),
        )

    async def main_turn(
        self, *, script: CallScript, history: list[dict], callee_speech: str, time_notice: str | None = None
    ) -> dict:
        payload = {"conversation_history": history, "callee_reply": callee_speech}
        return await self._ai.complete_json(
            system_prompt=_main_system_prompt(script, time_notice),
            user_content=json.dumps(payload),
        )

    async def generate_summary(self, *, script: CallScript, history: list[dict], extracted_fields: dict) -> dict:
        payload = {"conversation_history": history, "extracted_fields": extracted_fields}
        return await self._ai.complete_json(
            system_prompt=_summary_system_prompt(script),
            user_content=json.dumps(payload),
        )
