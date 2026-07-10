"""HTTP API for RubotPaul.

Endpoints reuse the existing ``CalendarService`` and ``NLPService``. All
``/api/v1`` routes require the vendored RubotPaul HMAC bearer token;
``/healthz`` is an unauthenticated liveness probe.

Calendar writes are destructive, so they follow the draft -> confirm ->
execute pattern (see PIVOT.md): the create/reschedule/delete endpoints
only *stage* a pending action; nothing touches Google Calendar until
RubotPaul relays the user's chat "confirm" via ``POST
/api/v1/events/confirm``. Pending actions live in an in-memory dict on
the app (single host) and expire after ``PENDING_TTL_SECONDS``.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import logging
import uuid
from typing import TYPE_CHECKING, Any

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
PENDING_TTL_SECONDS = 300

KIND_CREATE = "event_create"
KIND_RESCHEDULE = "event_reschedule"
KIND_DELETE = "event_delete"


@dataclasses.dataclass
class PendingAction:
    """A staged destructive action awaiting chat confirmation."""

    kind: str
    payload: dict[str, Any]
    expires_at: dt.datetime
    status: str = "pending"

    def is_expired(self, now: dt.datetime) -> bool:
        """Return True when the confirmation window has passed."""
        return now > self.expires_at


CALENDAR_KEY: web.AppKey[CalendarService] = web.AppKey("calendar")
NLP_KEY: web.AppKey[NLPService] = web.AppKey("nlp")
CALENDAR_IDS_KEY: web.AppKey[list[str]] = web.AppKey("calendar_ids")
PENDING_KEY: web.AppKey[dict[str, PendingAction]] = web.AppKey("pending_actions")


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


async def _json_object(request: web.Request) -> dict[str, Any]:
    """Parse the request body as a JSON object or raise ``_BadRequestError``."""
    try:
        body = await request.json()
    except json.JSONDecodeError as exc:
        raise _BadRequestError("invalid JSON body") from exc
    if not isinstance(body, dict):
        raise _BadRequestError("JSON body must be an object")
    return body


def _require_str(body: dict[str, Any], key: str) -> str:
    """Return a non-empty string field or raise ``_BadRequestError``."""
    value = body.get(key)
    if not isinstance(value, str) or not value.strip():
        msg = f"missing or invalid field: {key!r}"
        raise _BadRequestError(msg)
    return value.strip()


def _body_datetime(body: dict[str, Any], key: str) -> dt.datetime:
    """Parse an ISO-8601 body field; naive values are treated as UTC."""
    raw = body.get(key)
    if not isinstance(raw, str):
        msg = f"missing or invalid field: {key!r}"
        raise _BadRequestError(msg)
    try:
        parsed = dt.datetime.fromisoformat(raw)
    except ValueError as exc:
        msg = f"invalid {key!r}: expected ISO-8601 datetime"
        raise _BadRequestError(msg) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed


async def parse_intent(request: web.Request) -> web.Response:
    """Run the Claude NLP parser over free-form text."""
    try:
        body = await _json_object(request)
        text = _require_str(body, "text")
    except _BadRequestError as exc:
        return _error_response(str(exc))
    intent = await request.app[NLP_KEY].parse_message(text)
    return web.json_response(_intent_to_dict(intent))


# ---- Destructive endpoints (draft -> confirm -> execute) ------------------


def _stage(
    app: web.Application,
    kind: str,
    payload: dict[str, Any],
    preview: dict[str, Any],
) -> web.Response:
    """Store a pending action and return the pending_confirmation response."""
    action_id = str(uuid.uuid4())
    expires_at = dt.datetime.now(tz=dt.UTC) + dt.timedelta(seconds=PENDING_TTL_SECONDS)
    app[PENDING_KEY][action_id] = PendingAction(
        kind=kind, payload=payload, expires_at=expires_at
    )
    LOG.info("Staged %s as %s", kind, action_id)
    return web.json_response(
        {
            "status": "pending_confirmation",
            "action_id": action_id,
            "expires_in": PENDING_TTL_SECONDS,
            "preview": preview,
            "message": (
                "Staged. Post the draft in chat; after the user replies "
                "'confirm', call POST /api/v1/events/confirm."
            ),
        }
    )


def _resolve_calendar_id(calendar_ids: list[str], body: dict[str, Any]) -> str:
    """Return the target calendar, defaulting to the first configured one."""
    raw = body.get("calendar_id")
    if raw is None:
        return calendar_ids[0]
    if not isinstance(raw, str) or raw not in calendar_ids:
        raise _BadRequestError("unknown calendar_id")
    return raw


def _window(
    body: dict[str, Any], start_key: str, end_key: str
) -> tuple[dt.datetime, dt.datetime]:
    """Parse and validate an ordered [start, end) pair from the body."""
    start = _body_datetime(body, start_key)
    end = _body_datetime(body, end_key)
    if end <= start:
        msg = f"{end_key!r} must be after {start_key!r}"
        raise _BadRequestError(msg)
    return start, end


async def create_event(request: web.Request) -> web.Response:
    """Stage an event creation after checking for conflicts."""
    try:
        body = await _json_object(request)
        title = _require_str(body, "title")
        start, end = _window(body, "start", "end")
        calendar_id = _resolve_calendar_id(request.app[CALENDAR_IDS_KEY], body)
    except _BadRequestError as exc:
        return _error_response(str(exc))
    location = body.get("location")

    # Conflict check must precede staging (info-leak guard): a 409 here
    # reveals conflicts only for windows the caller could actually book.
    conflicts = await request.app[CALENDAR_KEY].find_conflicts(
        calendar_ids=request.app[CALENDAR_IDS_KEY],
        start_time=start,
        end_time=end,
    )
    if conflicts:
        return web.json_response(
            {
                "error": "conflict",
                "conflicts": [_event_to_dict(c) for c in conflicts],
            },
            status=409,
        )

    payload = {
        "calendar_id": calendar_id,
        "title": title,
        "start": start,
        "end": end,
        "location": location,
    }
    preview = {
        "kind": KIND_CREATE,
        "calendar_id": calendar_id,
        "title": title,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "location": location,
    }
    return _stage(request.app, KIND_CREATE, payload, preview)


async def reschedule_event(request: web.Request) -> web.Response:
    """Stage an event reschedule; the event must exist."""
    try:
        body = await _json_object(request)
        event_id = _require_str(body, "event_id")
        new_start, new_end = _window(body, "new_start", "new_end")
    except _BadRequestError as exc:
        return _error_response(str(exc))
    try:
        existing = await request.app[CALENDAR_KEY].get_event(
            calendar_ids=request.app[CALENDAR_IDS_KEY], event_id=event_id
        )
    except KeyError:
        return _error_response("event not found", status=404)

    payload = {
        "calendar_id": existing.calendar_id,
        "event_id": event_id,
        "new_start": new_start,
        "new_end": new_end,
        "title": existing.title,
    }
    preview = {
        "kind": KIND_RESCHEDULE,
        "event_id": event_id,
        "title": existing.title,
        "new_start": new_start.isoformat(),
        "new_end": new_end.isoformat(),
    }
    return _stage(request.app, KIND_RESCHEDULE, payload, preview)


async def delete_event(request: web.Request) -> web.Response:
    """Stage an event deletion; 404 when the event is unknown."""
    event_id = request.match_info["event_id"]
    try:
        existing = await request.app[CALENDAR_KEY].get_event(
            calendar_ids=request.app[CALENDAR_IDS_KEY], event_id=event_id
        )
    except KeyError:
        return _error_response("event not found", status=404)

    payload = {
        "calendar_id": existing.calendar_id,
        "event_id": event_id,
        "title": existing.title,
    }
    preview = {
        "kind": KIND_DELETE,
        "event_id": event_id,
        "title": existing.title,
    }
    return _stage(request.app, KIND_DELETE, payload, preview)


async def _apply_create(app: web.Application, action: PendingAction) -> web.Response:
    """Execute a staged event_create and mark the action approved."""
    payload = action.payload
    event = await app[CALENDAR_KEY].create_event(
        calendar_id=payload["calendar_id"],
        title=payload["title"],
        start_time=payload["start"],
        end_time=payload["end"],
        location=payload["location"],
    )
    action.status = "approved"
    return web.json_response({"status": "confirmed", "result": _event_to_dict(event)})


async def _apply_reschedule(
    app: web.Application, action: PendingAction
) -> web.Response:
    """Execute a staged event_reschedule and mark the action approved."""
    payload = action.payload
    event = await app[CALENDAR_KEY].update_event(
        calendar_id=payload["calendar_id"],
        event_id=payload["event_id"],
        start_time=payload["new_start"],
        end_time=payload["new_end"],
    )
    action.status = "approved"
    return web.json_response({"status": "confirmed", "result": _event_to_dict(event)})


async def _apply_delete(app: web.Application, action: PendingAction) -> web.Response:
    """Execute a staged event_delete; the action stays pending on failure."""
    payload = action.payload
    deleted = await app[CALENDAR_KEY].delete_event(
        calendar_id=payload["calendar_id"], event_id=payload["event_id"]
    )
    if not deleted:
        return _error_response("calendar delete failed; retry confirm", status=502)
    action.status = "approved"
    return web.json_response(
        {
            "status": "confirmed",
            "result": {"deleted": payload["event_id"], "title": payload["title"]},
        }
    )


_APPLIERS: dict[
    str, Callable[[web.Application, PendingAction], Awaitable[web.Response]]
] = {
    KIND_CREATE: _apply_create,
    KIND_RESCHEDULE: _apply_reschedule,
    KIND_DELETE: _apply_delete,
}


async def confirm_action(request: web.Request) -> web.Response:
    """Apply a staged action exactly once after chat confirmation."""
    try:
        body = await _json_object(request)
        action_id = _require_str(body, "action_id")
    except _BadRequestError as exc:
        return _error_response(str(exc))

    action = request.app[PENDING_KEY].get(action_id)
    if action is None:
        return _error_response("unknown action_id", status=404)
    if action.status != "pending":
        return _error_response("action already resolved", status=409)
    if action.is_expired(dt.datetime.now(tz=dt.UTC)):
        action.status = "expired"
        return _error_response("action expired", status=410)
    return await _APPLIERS[action.kind](request.app, action)


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
    api[PENDING_KEY] = {}
    api.router.add_get("/events", list_events)
    api.router.add_post("/events/parse", parse_intent)
    api.router.add_post("/events/create", create_event)
    api.router.add_post("/events/reschedule", reschedule_event)
    api.router.add_post("/events/confirm", confirm_action)
    api.router.add_delete("/events/{event_id}", delete_event)
    app.add_subapp("/api/v1", api)
    return app
