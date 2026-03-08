"""Data models for schedule intents and calendar events."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime


class IntentType(Enum):
    """Types of scheduling intents the bot can handle."""

    CREATE = "create"
    QUERY = "query"
    RESCHEDULE = "reschedule"
    DELETE = "delete"
    UNKNOWN = "unknown"


@dataclass
class FamilyMember:
    """A family member with their calendar information."""

    name: str
    email: str
    calendar_id: str


@dataclass
class ParsedIntent:
    """What Claude understood from the user's message."""

    intent: IntentType
    title: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    location: str | None = None
    people: list[FamilyMember] = field(default_factory=list)
    search_query: str | None = None
    raw_message: str = ""
    confidence: float = 1.0
    notes: str | None = None


@dataclass
class CalendarEvent:
    """An event from Google Calendar."""

    event_id: str
    calendar_id: str
    title: str
    start_time: datetime
    end_time: datetime
    location: str | None = None
    attendees: list[str] = field(default_factory=list)
    description: str | None = None

    @property
    def duration_str(self) -> str:
        """Return a human-readable duration string."""
        delta = self.end_time - self.start_time
        hours = delta.seconds // 3600
        minutes = (delta.seconds % 3600) // 60
        if hours and minutes:
            return f"{hours}h {minutes}m"
        if hours:
            return f"{hours}h"
        return f"{minutes}m"
