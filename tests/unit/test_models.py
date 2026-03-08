"""Tests for schedule_minion.models.events module."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from schedule_minion.models.events import (
    CalendarEvent,
    FamilyMember,
    IntentType,
    ParsedIntent,
)

TZ = ZoneInfo("America/Los_Angeles")


class TestIntentType:
    """Tests for IntentType enum."""

    def test_create_value(self) -> None:
        assert IntentType.CREATE.value == "create"

    def test_query_value(self) -> None:
        assert IntentType.QUERY.value == "query"

    def test_reschedule_value(self) -> None:
        assert IntentType.RESCHEDULE.value == "reschedule"

    def test_delete_value(self) -> None:
        assert IntentType.DELETE.value == "delete"

    def test_unknown_value(self) -> None:
        assert IntentType.UNKNOWN.value == "unknown"

    def test_from_string(self) -> None:
        assert IntentType("create") == IntentType.CREATE


class TestFamilyMember:
    """Tests for FamilyMember dataclass."""

    def test_create_family_member(self) -> None:
        member = FamilyMember(
            name="Dad",
            email="dad@example.com",
            calendar_id="dad@example.com",
        )
        assert member.name == "Dad"
        assert member.email == "dad@example.com"
        assert member.calendar_id == "dad@example.com"


class TestParsedIntent:
    """Tests for ParsedIntent dataclass."""

    def test_defaults(self) -> None:
        intent = ParsedIntent(intent=IntentType.UNKNOWN)
        assert intent.title is None
        assert intent.start_time is None
        assert intent.end_time is None
        assert intent.location is None
        assert intent.people == []
        assert intent.search_query is None
        assert intent.raw_message == ""
        assert intent.confidence == 1.0
        assert intent.notes is None

    def test_create_intent_with_all_fields(self) -> None:
        now = datetime.now(TZ)
        member = FamilyMember(
            name="Dad", email="dad@example.com", calendar_id="dad@example.com"
        )
        intent = ParsedIntent(
            intent=IntentType.CREATE,
            title="Pizza Night",
            start_time=now,
            end_time=now + timedelta(hours=1),
            location="Home",
            people=[member],
            raw_message="Pizza tonight at home",
            confidence=0.95,
            notes="Family dinner",
        )
        assert intent.intent == IntentType.CREATE
        assert intent.title == "Pizza Night"
        assert intent.location == "Home"
        assert len(intent.people) == 1
        assert intent.people[0].name == "Dad"


class TestCalendarEvent:
    """Tests for CalendarEvent dataclass."""

    def test_create_event(self) -> None:
        now = datetime.now(TZ)
        event = CalendarEvent(
            event_id="test-123",
            calendar_id="cal@example.com",
            title="Date Night",
            start_time=now,
            end_time=now + timedelta(hours=3),
        )
        assert event.event_id == "test-123"
        assert event.title == "Date Night"
        assert event.attendees == []

    def test_duration_str_hours_and_minutes(self) -> None:
        now = datetime.now(TZ)
        event = CalendarEvent(
            event_id="1",
            calendar_id="cal",
            title="Test",
            start_time=now,
            end_time=now + timedelta(hours=1, minutes=30),
        )
        assert event.duration_str == "1h 30m"

    def test_duration_str_hours_only(self) -> None:
        now = datetime.now(TZ)
        event = CalendarEvent(
            event_id="1",
            calendar_id="cal",
            title="Test",
            start_time=now,
            end_time=now + timedelta(hours=2),
        )
        assert event.duration_str == "2h"

    def test_duration_str_minutes_only(self) -> None:
        now = datetime.now(TZ)
        event = CalendarEvent(
            event_id="1",
            calendar_id="cal",
            title="Test",
            start_time=now,
            end_time=now + timedelta(minutes=45),
        )
        assert event.duration_str == "45m"

    def test_event_with_attendees(self) -> None:
        now = datetime.now(TZ)
        event = CalendarEvent(
            event_id="1",
            calendar_id="cal",
            title="Test",
            start_time=now,
            end_time=now + timedelta(hours=1),
            attendees=["a@example.com", "b@example.com"],
        )
        assert len(event.attendees) == 2
