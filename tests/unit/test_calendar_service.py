"""Tests for schedule_minion.services.calendar_service module."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from schedule_minion.constants import ALL_FAMILY
from schedule_minion.services.calendar_service import (
    CalendarService,
    _build_attendee_line,
    _parse_attendees_from_description,
)

TZ = ZoneInfo("America/Los_Angeles")


@pytest.fixture
def service() -> CalendarService:
    """Create a CalendarService with mocked Google API."""
    svc = CalendarService(
        credentials_path="fake-path.json", timezone="America/Los_Angeles"
    )
    # Pre-set a mock service so _get_service() doesn't try real credentials
    mock_api = MagicMock()
    svc._service = mock_api
    return svc


class TestCreateEvent:
    """Tests for CalendarService.create_event."""

    @pytest.mark.asyncio
    async def test_returns_calendar_event(self, service: CalendarService) -> None:
        now = datetime.now(TZ)
        mock_execute = MagicMock(
            return_value={"id": "new-123", "summary": "Test Event"}
        )
        service._service.events.return_value.insert.return_value.execute = mock_execute

        event = await service.create_event(
            calendar_id="test@group.calendar.google.com",
            title="Test Event",
            start_time=now,
            end_time=now + timedelta(hours=1),
            attendees=list(ALL_FAMILY),
        )

        assert event.event_id == "new-123"
        assert event.title == "Test Event"
        assert len(event.attendees) == len(ALL_FAMILY)

    @pytest.mark.asyncio
    async def test_with_location(self, service: CalendarService) -> None:
        now = datetime.now(TZ)
        mock_execute = MagicMock(return_value={"id": "loc-1", "summary": "Dinner"})
        service._service.events.return_value.insert.return_value.execute = mock_execute

        event = await service.create_event(
            calendar_id="cal",
            title="Dinner",
            start_time=now,
            end_time=now + timedelta(hours=2),
            location="Olive Garden",
        )

        assert event.location == "Olive Garden"

    @pytest.mark.asyncio
    async def test_without_attendees(self, service: CalendarService) -> None:
        now = datetime.now(TZ)
        mock_execute = MagicMock(return_value={"id": "solo-1", "summary": "Solo Event"})
        service._service.events.return_value.insert.return_value.execute = mock_execute

        event = await service.create_event(
            calendar_id="cal",
            title="Solo Event",
            start_time=now,
            end_time=now + timedelta(hours=1),
        )

        assert event.attendees == []


class TestGetEvents:
    """Tests for CalendarService.get_events."""

    @pytest.mark.asyncio
    async def test_returns_list(self, service: CalendarService) -> None:
        mock_execute = MagicMock(return_value={"items": []})
        service._service.events.return_value.list.return_value.execute = mock_execute

        now = datetime.now(TZ)
        events = await service.get_events(
            calendar_ids=["cal"],
            time_min=now,
            time_max=now + timedelta(days=7),
        )

        assert isinstance(events, list)
        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_returns_events_from_api(self, service: CalendarService) -> None:
        mock_execute = MagicMock(
            return_value={
                "items": [
                    {
                        "id": "e1",
                        "summary": "Soccer Practice",
                        "start": {"dateTime": "2026-03-03T16:00:00-08:00"},
                        "end": {"dateTime": "2026-03-03T17:00:00-08:00"},
                        "location": "Fields",
                    }
                ]
            }
        )
        service._service.events.return_value.list.return_value.execute = mock_execute

        now = datetime.now(TZ)
        events = await service.get_events(
            calendar_ids=["cal"],
            time_min=now,
            time_max=now + timedelta(days=7),
        )

        assert len(events) == 1
        assert events[0].title == "Soccer Practice"
        assert events[0].location == "Fields"

    @pytest.mark.asyncio
    async def test_deduplicates_across_calendars(
        self, service: CalendarService
    ) -> None:
        mock_execute = MagicMock(
            return_value={
                "items": [
                    {
                        "id": "same-id",
                        "summary": "Shared Event",
                        "start": {"dateTime": "2026-03-03T10:00:00-08:00"},
                        "end": {"dateTime": "2026-03-03T11:00:00-08:00"},
                    }
                ]
            }
        )
        service._service.events.return_value.list.return_value.execute = mock_execute

        now = datetime.now(TZ)
        events = await service.get_events(
            calendar_ids=["cal1", "cal2"],
            time_min=now,
            time_max=now + timedelta(days=7),
        )

        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_handles_api_error_gracefully(self, service: CalendarService) -> None:
        service._service.events.return_value.list.return_value.execute = MagicMock(
            side_effect=RuntimeError("API error")
        )

        now = datetime.now(TZ)
        events = await service.get_events(
            calendar_ids=["cal"],
            time_min=now,
            time_max=now + timedelta(days=7),
        )

        assert events == []

    @pytest.mark.asyncio
    async def test_parses_attendees(self, service: CalendarService) -> None:
        mock_execute = MagicMock(
            return_value={
                "items": [
                    {
                        "id": "e1",
                        "summary": "Meeting",
                        "start": {"dateTime": "2026-03-03T16:00:00-08:00"},
                        "end": {"dateTime": "2026-03-03T17:00:00-08:00"},
                        "attendees": [
                            {"email": "a@example.com"},
                            {"email": "b@example.com"},
                        ],
                    }
                ]
            }
        )
        service._service.events.return_value.list.return_value.execute = mock_execute

        now = datetime.now(TZ)
        events = await service.get_events(
            calendar_ids=["cal"],
            time_min=now,
            time_max=now + timedelta(days=7),
        )

        assert len(events[0].attendees) == 2


class TestDeleteEvent:
    """Tests for CalendarService.delete_event."""

    @pytest.mark.asyncio
    async def test_returns_true_on_success(self, service: CalendarService) -> None:
        mock_execute = MagicMock(return_value=None)
        service._service.events.return_value.delete.return_value.execute = mock_execute

        result = await service.delete_event(calendar_id="cal", event_id="event-123")

        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_on_error(self, service: CalendarService) -> None:
        service._service.events.return_value.delete.return_value.execute = MagicMock(
            side_effect=RuntimeError("fail")
        )

        result = await service.delete_event(calendar_id="cal", event_id="event-123")

        assert result is False


class TestUpdateEvent:
    """Tests for CalendarService.update_event."""

    @pytest.mark.asyncio
    async def test_updates_and_returns_event(self, service: CalendarService) -> None:
        now = datetime.now(TZ)
        existing = {
            "id": "event-123",
            "summary": "Old Title",
            "start": {"dateTime": "2026-03-03T10:00:00-08:00"},
            "end": {"dateTime": "2026-03-03T11:00:00-08:00"},
        }
        updated = {
            "id": "event-123",
            "summary": "New Title",
            "start": {"dateTime": now.isoformat()},
            "end": {"dateTime": (now + timedelta(hours=1)).isoformat()},
        }

        service._service.events.return_value.get.return_value.execute = MagicMock(
            return_value=existing
        )
        service._service.events.return_value.update.return_value.execute = MagicMock(
            return_value=updated
        )

        event = await service.update_event(
            calendar_id="cal",
            event_id="event-123",
            title="New Title",
            start_time=now,
            end_time=now + timedelta(hours=1),
        )

        assert event.event_id == "event-123"
        assert event.title == "New Title"

    @pytest.mark.asyncio
    async def test_update_with_location(self, service: CalendarService) -> None:
        now = datetime.now(TZ)
        existing = {
            "id": "e1",
            "summary": "Event",
            "start": {"dateTime": now.isoformat()},
            "end": {"dateTime": (now + timedelta(hours=1)).isoformat()},
        }
        updated = {
            "id": "e1",
            "summary": "Event",
            "start": {"dateTime": now.isoformat()},
            "end": {"dateTime": (now + timedelta(hours=1)).isoformat()},
            "location": "Park",
        }

        service._service.events.return_value.get.return_value.execute = MagicMock(
            return_value=existing
        )
        service._service.events.return_value.update.return_value.execute = MagicMock(
            return_value=updated
        )

        event = await service.update_event(
            calendar_id="cal",
            event_id="e1",
            start_time=now,
            end_time=now + timedelta(hours=1),
            location="Park",
        )

        assert event.location == "Park"


class TestFindConflicts:
    """Tests for CalendarService.find_conflicts."""

    @pytest.mark.asyncio
    async def test_returns_overlapping_events(self, service: CalendarService) -> None:
        mock_execute = MagicMock(
            return_value={
                "items": [
                    {
                        "id": "conflict-1",
                        "summary": "Existing Event",
                        "start": {"dateTime": "2026-03-03T15:00:00-08:00"},
                        "end": {"dateTime": "2026-03-03T16:00:00-08:00"},
                    }
                ]
            }
        )
        service._service.events.return_value.list.return_value.execute = mock_execute

        now = datetime(2026, 3, 3, 14, 30, tzinfo=TZ)
        conflicts = await service.find_conflicts(
            calendar_ids=["cal"],
            start_time=now,
            end_time=now + timedelta(hours=2),
        )

        assert len(conflicts) == 1
        assert conflicts[0].title == "Existing Event"


class TestBuildAttendeeLine:
    """Tests for _build_attendee_line helper."""

    def test_builds_line_from_members(self) -> None:
        result = _build_attendee_line(list(ALL_FAMILY))
        assert result == "Attendees: Dad, Mom, Layla, Niall"

    def test_single_member(self) -> None:
        result = _build_attendee_line([ALL_FAMILY[0]])
        assert result == "Attendees: Dad"


class TestParseAttendeesFromDescription:
    """Tests for _parse_attendees_from_description helper."""

    def test_parses_attendee_line(self) -> None:
        desc = "Attendees: Dad, Mom, Layla"
        assert _parse_attendees_from_description(desc) == ["Dad", "Mom", "Layla"]

    def test_returns_empty_for_none(self) -> None:
        assert _parse_attendees_from_description(None) == []

    def test_returns_empty_for_no_attendee_line(self) -> None:
        assert _parse_attendees_from_description("Just a regular description") == []

    def test_handles_multiline_description(self) -> None:
        desc = "Some notes about the event\nAttendees: Dad, Niall"
        assert _parse_attendees_from_description(desc) == ["Dad", "Niall"]

    def test_handles_empty_string(self) -> None:
        assert _parse_attendees_from_description("") == []


class TestCreateEventDescription:
    """Tests for attendee names being stored in event description."""

    @pytest.mark.asyncio
    async def test_creates_description_with_attendees(
        self, service: CalendarService
    ) -> None:
        now = datetime.now(TZ)
        mock_execute = MagicMock(
            return_value={
                "id": "desc-1",
                "summary": "Soccer",
                "description": "Attendees: Dad, Layla",
            }
        )
        service._service.events.return_value.insert.return_value.execute = mock_execute

        event = await service.create_event(
            calendar_id="cal",
            title="Soccer",
            start_time=now,
            end_time=now + timedelta(hours=1),
            attendees=[ALL_FAMILY[0], ALL_FAMILY[2]],  # Dad, Layla
        )

        assert event.attendees == ["Dad", "Layla"]
        assert event.description == "Attendees: Dad, Layla"

        # Verify description was sent in the API body
        call_args = service._service.events.return_value.insert.call_args
        body = call_args.kwargs.get("body") or call_args[1].get("body")
        assert body["description"] == "Attendees: Dad, Layla"

    @pytest.mark.asyncio
    async def test_no_description_without_attendees(
        self, service: CalendarService
    ) -> None:
        now = datetime.now(TZ)
        mock_execute = MagicMock(
            return_value={"id": "no-desc-1", "summary": "Solo Event"}
        )
        service._service.events.return_value.insert.return_value.execute = mock_execute

        event = await service.create_event(
            calendar_id="cal",
            title="Solo Event",
            start_time=now,
            end_time=now + timedelta(hours=1),
        )

        assert event.attendees == []
        assert event.description is None


class TestGetEventsDescription:
    """Tests for parsing attendees from event descriptions."""

    @pytest.mark.asyncio
    async def test_parses_attendees_from_description(
        self, service: CalendarService
    ) -> None:
        mock_execute = MagicMock(
            return_value={
                "items": [
                    {
                        "id": "e1",
                        "summary": "Soccer Practice",
                        "start": {"dateTime": "2026-03-03T16:00:00-08:00"},
                        "end": {"dateTime": "2026-03-03T17:00:00-08:00"},
                        "description": "Attendees: Dad, Layla",
                    }
                ]
            }
        )
        service._service.events.return_value.list.return_value.execute = mock_execute

        now = datetime.now(TZ)
        events = await service.get_events(
            calendar_ids=["cal"],
            time_min=now,
            time_max=now + timedelta(days=7),
        )

        assert events[0].attendees == ["Dad", "Layla"]
        assert events[0].description == "Attendees: Dad, Layla"

    @pytest.mark.asyncio
    async def test_falls_back_to_email_attendees(
        self, service: CalendarService
    ) -> None:
        mock_execute = MagicMock(
            return_value={
                "items": [
                    {
                        "id": "e1",
                        "summary": "Meeting",
                        "start": {"dateTime": "2026-03-03T16:00:00-08:00"},
                        "end": {"dateTime": "2026-03-03T17:00:00-08:00"},
                        "attendees": [{"email": "a@example.com"}],
                    }
                ]
            }
        )
        service._service.events.return_value.list.return_value.execute = mock_execute

        now = datetime.now(TZ)
        events = await service.get_events(
            calendar_ids=["cal"],
            time_min=now,
            time_max=now + timedelta(days=7),
        )

        assert events[0].attendees == ["a@example.com"]

    @pytest.mark.asyncio
    async def test_no_description_no_attendees(self, service: CalendarService) -> None:
        mock_execute = MagicMock(
            return_value={
                "items": [
                    {
                        "id": "e1",
                        "summary": "Solo",
                        "start": {"dateTime": "2026-03-03T16:00:00-08:00"},
                        "end": {"dateTime": "2026-03-03T17:00:00-08:00"},
                    }
                ]
            }
        )
        service._service.events.return_value.list.return_value.execute = mock_execute

        now = datetime.now(TZ)
        events = await service.get_events(
            calendar_ids=["cal"],
            time_min=now,
            time_max=now + timedelta(days=7),
        )

        assert events[0].attendees == []


class TestUpdateEventDescription:
    """Tests for update_event preserving description/attendees."""

    @pytest.mark.asyncio
    async def test_preserves_attendees_on_update(
        self, service: CalendarService
    ) -> None:
        now = datetime.now(TZ)
        existing = {
            "id": "e1",
            "summary": "Soccer",
            "description": "Attendees: Dad, Layla",
            "start": {"dateTime": now.isoformat()},
            "end": {"dateTime": (now + timedelta(hours=1)).isoformat()},
        }
        updated = {
            "id": "e1",
            "summary": "Soccer",
            "description": "Attendees: Dad, Layla",
            "start": {"dateTime": (now + timedelta(days=1)).isoformat()},
            "end": {"dateTime": (now + timedelta(days=1, hours=1)).isoformat()},
        }

        service._service.events.return_value.get.return_value.execute = MagicMock(
            return_value=existing
        )
        service._service.events.return_value.update.return_value.execute = MagicMock(
            return_value=updated
        )

        event = await service.update_event(
            calendar_id="cal",
            event_id="e1",
            start_time=now + timedelta(days=1),
            end_time=now + timedelta(days=1, hours=1),
        )

        assert event.attendees == ["Dad", "Layla"]
        assert event.description == "Attendees: Dad, Layla"
