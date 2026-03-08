"""Parses natural language messages into structured intents via Claude API."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import anthropic
from anthropic.types import TextBlock

from schedule_minion.constants import ALL_FAMILY, FAMILY_MEMBERS, NAME_ALIASES
from schedule_minion.models.events import FamilyMember, IntentType, ParsedIntent

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are the brain of a family Discord bot called "Schedule Minion." Your job is \
to parse natural language messages about scheduling into structured JSON.

## Family Members
- Dad (Geoff) — Geoffe.gallinger@gmail.com
- Mom (Free) — Freelalala@gmail.com
- Layla — One.Bad.Baldie@gmail.com
- Niall — ANiallation@gmail.com

## Rules
1. Determine the intent: "create", "query", "reschedule", "delete", or "unknown"
2. For CREATE intents:
   - Generate a short, cute event title (2-4 words max). Be a little playful.
   - Parse start time and end time. Default to 1 hour duration if no end time given.
   - If no people are mentioned, assume the WHOLE FAMILY.
   - Extract location if mentioned.
3. For QUERY intents:
   - Parse the time range being asked about.
   - Identify which people are being asked about (default: whole family).
4. For RESCHEDULE intents:
   - Include search_query (name of event to find) AND the new time.
5. For DELETE intents:
   - Include search_query (name of event to find).
6. Use the family member names/aliases to identify people. "We" means the whole family.

## Output Format
Respond with ONLY valid JSON, no markdown, no explanation:
{
  "intent": "create" | "query" | "reschedule" | "delete" | "unknown",
  "title": "Event Name" | null,
  "start_time": "ISO 8601 datetime" | null,
  "end_time": "ISO 8601 datetime" | null,
  "location": "string" | null,
  "people": ["dad", "mom", "layla", "niall"] | [],
  "search_query": "string to match event title" | null,
  "notes": "any extra context" | null
}

IMPORTANT: If people is empty or not specified, it means the whole family.\
"""


class NLPService:
    """Natural language parsing service using Claude API."""

    def __init__(self, api_key: str, timezone: str) -> None:
        self.client = anthropic.AsyncAnthropic(api_key=api_key)
        self.timezone = timezone

    async def parse_message(self, message: str) -> ParsedIntent:
        """Parse a natural language message into a structured intent.

        Args:
            message: The user's natural language message.

        Returns:
            A ParsedIntent describing the user's scheduling request.

        Raises:
            json.JSONDecodeError: If Claude's response is not valid JSON.
            anthropic.APIError: If the Claude API call fails.
        """
        now = datetime.now(ZoneInfo(self.timezone))
        user_prompt = (
            f"Current date and time: "
            f"{now.strftime('%A, %B %d, %Y at %I:%M %p %Z')}\n"
            f"Timezone: {self.timezone}\n\n"
            f"User message: {message}"
        )

        response = await self.client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=500,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )

        content_block = response.content[0]
        if not isinstance(content_block, TextBlock):
            msg = f"Expected TextBlock, got {type(content_block).__name__}"
            raise TypeError(msg)
        raw_text = content_block.text.strip()

        # Strip markdown code fences if Claude adds them
        if raw_text.startswith("```"):
            raw_text = raw_text.split("\n", 1)[1]
            if raw_text.endswith("```"):
                raw_text = raw_text[:-3]
            raw_text = raw_text.strip()

        data = json.loads(raw_text)

        people = self._resolve_people(data.get("people", []))

        start_time = (
            datetime.fromisoformat(data["start_time"])
            if data.get("start_time")
            else None
        )
        end_time = (
            datetime.fromisoformat(data["end_time"]) if data.get("end_time") else None
        )

        return ParsedIntent(
            intent=IntentType(data["intent"]),
            title=data.get("title"),
            start_time=start_time,
            end_time=end_time,
            location=data.get("location"),
            people=people,
            search_query=data.get("search_query"),
            raw_message=message,
            notes=data.get("notes"),
        )

    @staticmethod
    def _resolve_people(names: list[str]) -> list[FamilyMember]:
        """Resolve people names/aliases to FamilyMember objects."""
        if not names:
            return list(ALL_FAMILY)

        people: list[FamilyMember] = []
        for name in names:
            key = name.lower()
            if key in NAME_ALIASES:
                key = NAME_ALIASES[key]
            if key in FAMILY_MEMBERS:
                people.append(FAMILY_MEMBERS[key])

        return people if people else list(ALL_FAMILY)
