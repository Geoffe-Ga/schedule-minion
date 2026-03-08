"""Google Calendar API wrapper."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from functools import partial

from google.oauth2 import service_account
from googleapiclient.discovery import build  # type: ignore[import-untyped]

from schedule_minion.models.events import CalendarEvent, FamilyMember

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar"]

ATTENDEES_PREFIX = "Attendees: "


def _build_attendee_line(members: list[FamilyMember]) -> str:
    """Build an 'Attendees: ...' line from family members."""
    return ATTENDEES_PREFIX + ", ".join(m.name for m in members)


def _parse_attendees_from_description(description: str | None) -> list[str]:
    """Extract attendee names from an event description.

    Looks for a line starting with 'Attendees: ' and splits on commas.
    Returns an empty list if no such line is found.
    """
    if not description:
        return []
    for line in description.splitlines():
        if line.startswith(ATTENDEES_PREFIX):
            names_part = line[len(ATTENDEES_PREFIX) :]
            return [n.strip() for n in names_part.split(",") if n.strip()]
    return []


class CalendarService:
    """Manages Google Calendar events via the Google Calendar API."""

    def __init__(self, credentials_path: str, timezone: str) -> None:
        self.timezone = timezone
        self._credentials_path = credentials_path
        self._service = None

    def _get_service(self):  # type: ignore[no-untyped-def]
        """Lazily initialize the Google Calendar API service."""
        if self._service is None:
            credentials = service_account.Credentials.from_service_account_file(
                self._credentials_path, scopes=SCOPES
            )
            self._service = build("calendar", "v3", credentials=credentials)
        return self._service

    async def _run_sync(self, func, *args, **kwargs):  # type: ignore[no-untyped-def]
        """Run a synchronous Google API call in a thread pool."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, partial(func, *args, **kwargs))

    async def create_event(
        self,
        calendar_id: str,
        title: str,
        start_time: datetime,
        end_time: datetime,
        attendees: list[FamilyMember] | None = None,
        location: str | None = None,
    ) -> CalendarEvent:
        """Create a calendar event.

        Args:
            calendar_id: The target calendar ID.
            title: Event title.
            start_time: Event start time.
            end_time: Event end time.
            attendees: Optional list of family members to invite.
            location: Optional event location.

        Returns:
            The created CalendarEvent.
        """
        event_body: dict = {
            "summary": title,
            "start": {
                "dateTime": start_time.isoformat(),
                "timeZone": self.timezone,
            },
            "end": {
                "dateTime": end_time.isoformat(),
                "timeZone": self.timezone,
            },
        }

        if location:
            event_body["location"] = location

        # Service accounts can't invite attendees via the API without
        # domain-wide delegation, so we persist names in the description.
        if attendees:
            event_body["description"] = _build_attendee_line(attendees)

        service = self._get_service()
        result = await self._run_sync(
            service.events().insert(calendarId=calendar_id, body=event_body).execute
        )

        description = result.get("description")
        attendee_names = [m.name for m in attendees] if attendees else []

        return CalendarEvent(
            event_id=result["id"],
            calendar_id=calendar_id,
            title=result["summary"],
            start_time=start_time,
            end_time=end_time,
            location=location,
            attendees=attendee_names,
            description=description,
        )

    async def get_events(
        self,
        calendar_ids: list[str],
        time_min: datetime,
        time_max: datetime,
    ) -> list[CalendarEvent]:
        """Get events from one or more calendars within a time range.

        Args:
            calendar_ids: Calendar IDs to query.
            time_min: Start of time range.
            time_max: End of time range.

        Returns:
            List of CalendarEvent objects, sorted by start time.
        """
        all_events: list[CalendarEvent] = []
        seen_ids: set[str] = set()

        service = self._get_service()
        for cal_id in calendar_ids:
            try:
                result = await self._run_sync(
                    service.events()
                    .list(
                        calendarId=cal_id,
                        timeMin=time_min.isoformat(),
                        timeMax=time_max.isoformat(),
                        singleEvents=True,
                        orderBy="startTime",
                    )
                    .execute
                )

                for item in result.get("items", []):
                    if item["id"] in seen_ids:
                        continue
                    seen_ids.add(item["id"])

                    start = item["start"].get("dateTime", item["start"].get("date"))
                    end = item["end"].get("dateTime", item["end"].get("date"))

                    description = item.get("description")
                    attendees = _parse_attendees_from_description(description)
                    if not attendees:
                        attendees = [a["email"] for a in item.get("attendees", [])]

                    all_events.append(
                        CalendarEvent(
                            event_id=item["id"],
                            calendar_id=cal_id,
                            title=item.get("summary", "Untitled"),
                            start_time=datetime.fromisoformat(start),
                            end_time=datetime.fromisoformat(end),
                            location=item.get("location"),
                            attendees=attendees,
                            description=description,
                        )
                    )
            except Exception:
                logger.exception("Failed to fetch events from %s", cal_id)

        return sorted(all_events, key=lambda e: e.start_time)

    async def delete_event(self, calendar_id: str, event_id: str) -> bool:
        """Delete a calendar event.

        Args:
            calendar_id: The calendar containing the event.
            event_id: The event to delete.

        Returns:
            True if deletion succeeded, False otherwise.
        """
        try:
            service = self._get_service()
            await self._run_sync(
                service.events()
                .delete(calendarId=calendar_id, eventId=event_id)
                .execute
            )
        except Exception:
            logger.exception("Failed to delete event %s", event_id)
            return False
        else:
            return True

    async def update_event(
        self,
        calendar_id: str,
        event_id: str,
        title: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        location: str | None = None,
    ) -> CalendarEvent:
        """Update an existing calendar event.

        Args:
            calendar_id: The calendar containing the event.
            event_id: The event to update.
            title: New title (optional).
            start_time: New start time (optional).
            end_time: New end time (optional).
            location: New location (optional).

        Returns:
            The updated CalendarEvent.
        """
        service = self._get_service()

        existing = await self._run_sync(
            service.events().get(calendarId=calendar_id, eventId=event_id).execute
        )

        if title:
            existing["summary"] = title
        if start_time:
            existing["start"] = {
                "dateTime": start_time.isoformat(),
                "timeZone": self.timezone,
            }
        if end_time:
            existing["end"] = {
                "dateTime": end_time.isoformat(),
                "timeZone": self.timezone,
            }
        if location:
            existing["location"] = location

        result = await self._run_sync(
            service.events()
            .update(
                calendarId=calendar_id,
                eventId=event_id,
                body=existing,
            )
            .execute
        )

        description = result.get("description")
        attendees = _parse_attendees_from_description(description)

        return CalendarEvent(
            event_id=result["id"],
            calendar_id=calendar_id,
            title=result.get("summary", "Untitled"),
            start_time=start_time
            or datetime.fromisoformat(
                result["start"].get("dateTime", result["start"]["date"])
            ),
            end_time=end_time
            or datetime.fromisoformat(
                result["end"].get("dateTime", result["end"]["date"])
            ),
            location=result.get("location"),
            attendees=attendees,
            description=description,
        )

    async def find_conflicts(
        self,
        calendar_ids: list[str],
        start_time: datetime,
        end_time: datetime,
    ) -> list[CalendarEvent]:
        """Find events that overlap with the proposed time window.

        Args:
            calendar_ids: Calendar IDs to check for conflicts.
            start_time: Proposed start time.
            end_time: Proposed end time.

        Returns:
            List of conflicting CalendarEvent objects.
        """
        return await self.get_events(
            calendar_ids=calendar_ids,
            time_min=start_time,
            time_max=end_time,
        )
