"""HTTP API for RubotPaul.

Read-only endpoints that reuse the existing ``CalendarService`` and
``NLPService``. All ``/api/v1`` routes require the vendored RubotPaul
HMAC bearer token; ``/healthz`` is an unauthenticated liveness probe.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from typing import TYPE_CHECKING

from aiohttp import web

from schedule_minion.auth_middleware import aiohttp_auth_middleware

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from schedule_minion.models.events import CalendarEvent, ParsedIntent
    from schedule_minion.services.calendar_service import CalendarService
    from schedule_minion.services.nlp_service import NLPService

    Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]

LOG = logging.getLogger(__name__)

DEFAULT_WINDOW_DAYS = 7
MAX_WINDOW_DAYS = 60

CALENDAR_KEY: web.AppKey[CalendarService] = web.AppKey("calendar")
NLP_KEY: web.AppKey[NLPService] = web.AppKey("nlp")
CALENDAR_IDS_KEY: web.AppKey[list[str]] = web.AppKey("calendar_ids")


class _BadRequestError(Exception):
    """Raised by request-parsing helpers to signal a 400 response."""


def _error_response(message: str, status: int = 400) -> web.Response:
    return web.json_response({"error": message}, status=status)


def _parse_query_datetime(request: web.Request, param: str) -> dt.datetime | None:
    """Parse an ISO-8601 query parameter; naive values are treated as UTC."""
    raw = request.query.get(param)
    if raw is None:
        return None
    try:
        parsed = dt.datetime.fromisoformat(raw)
    except ValueError as exc:
        msg = f"invalid {param!r}: expected ISO-8601 datetime"
        raise _BadRequestError(msg) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed


def _resolve_window(request: web.Request) -> tuple[dt.datetime, dt.datetime]:
    """Resolve the [from, to] query window, defaulting to now -> now+7d."""
    start = _parse_query_datetime(request, "from")
    if start is None:
        start = dt.datetime.now(tz=dt.UTC)
    end = _parse_query_datetime(request, "to")
    if end is None:
        end = start + dt.timedelta(days=DEFAULT_WINDOW_DAYS)
    if end < start:
        msg = "invalid window: 'to' is before 'from'"
        raise _BadRequestError(msg)
    if end - start > dt.timedelta(days=MAX_WINDOW_DAYS):
        msg = f"window exceeds {MAX_WINDOW_DAYS} days"
        raise _BadRequestError(msg)
    return start, end


def _event_to_dict(event: CalendarEvent) -> dict[str, object]:
    return {
        "id": event.event_id,
        "calendar_id": event.calendar_id,
        "title": event.title,
        "start": event.start_time.isoformat(),
        "end": event.end_time.isoformat(),
        "location": event.location or "",
        "attendees": list(event.attendees),
        "description": event.description or "",
    }


def _intent_to_dict(intent: ParsedIntent) -> dict[str, object]:
    return {
        "intent": intent.intent.value,
        "confidence": intent.confidence,
        "fields": {
            "title": intent.title,
            "start_time": intent.start_time.isoformat() if intent.start_time else None,
            "end_time": intent.end_time.isoformat() if intent.end_time else None,
            "location": intent.location,
            "people": [member.name for member in intent.people],
            "search_query": intent.search_query,
            "notes": intent.notes,
        },
    }


async def healthz(_request: web.Request) -> web.Response:
    """Unauthenticated liveness probe."""
    return web.json_response({"ok": True})


async def list_events(request: web.Request) -> web.Response:
    """Return events in the requested window from the configured calendars."""
    try:
        start, end = _resolve_window(request)
    except _BadRequestError as exc:
        return _error_response(str(exc))
    calendar = request.app[CALENDAR_KEY]
    events = await calendar.get_events(
        calendar_ids=request.app[CALENDAR_IDS_KEY],
        time_min=start,
        time_max=end,
    )
    return web.json_response(
        {
            "from": start.isoformat(),
            "to": end.isoformat(),
            "events": [_event_to_dict(event) for event in events],
        }
    )


async def parse_intent(request: web.Request) -> web.Response:
    """Run the Claude NLP parser over free-form text."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return _error_response("invalid JSON body")
    if not isinstance(body, dict):
        return _error_response("JSON body must be an object")
    text = body.get("text")
    if not isinstance(text, str) or not text.strip():
        return _error_response("text required")
    intent = await request.app[NLP_KEY].parse_message(text.strip())
    return web.json_response(_intent_to_dict(intent))


@web.middleware
async def _auth_middleware(
    request: web.Request, handler: Handler
) -> web.StreamResponse:
    """New-style adapter around the vendored old-style middleware factory."""
    wrapped = await aiohttp_auth_middleware(request.app, handler)
    return await wrapped(request)


def build_app(
    *,
    calendar: CalendarService,
    nlp: NLPService,
    calendar_ids: list[str],
) -> web.Application:
    """Build the aiohttp application with injected services.

    Args:
        calendar: The calendar service used to list events.
        nlp: The NLP service used to parse free-form text.
        calendar_ids: Google calendar IDs queried by ``GET /api/v1/events``.

    Returns:
        The configured application: unauthenticated ``/healthz`` plus the
        HMAC-protected ``/api/v1`` subapp.
    """
    app = web.Application()
    app.router.add_get("/healthz", healthz)

    api = web.Application(middlewares=[_auth_middleware])
    api[CALENDAR_KEY] = calendar
    api[NLP_KEY] = nlp
    api[CALENDAR_IDS_KEY] = list(calendar_ids)
    api.router.add_get("/events", list_events)
    api.router.add_post("/events/parse", parse_intent)
    app.add_subapp("/api/v1", api)
    return app
