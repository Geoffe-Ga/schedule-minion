"""Tests for schedule_minion.api module."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest
from aiohttp.test_utils import TestClient, TestServer

from schedule_minion.api import build_app
from schedule_minion.auth_middleware import SECRET_ENV_VAR, mint_token
from schedule_minion.models.events import (
    CalendarEvent,
    FamilyMember,
    IntentType,
    ParsedIntent,
)

if TYPE_CHECKING:
    from aiohttp import web

TEST_SECRET = "test-shared-secret"
CALENDAR_IDS = ["family@example.com"]


def _make_event(**overrides: object) -> CalendarEvent:
    defaults: dict = {
        "event_id": "evt-1",
        "calendar_id": CALENDAR_IDS[0],
        "title": "Dentist Dash",
        "start_time": datetime(2026, 7, 10, 9, 0, tzinfo=UTC),
        "end_time": datetime(2026, 7, 10, 10, 0, tzinfo=UTC),
        "location": "123 Molar St",
        "attendees": ["Dad", "Layla"],
        "description": "Attendees: Dad, Layla",
    }
    defaults.update(overrides)
    return CalendarEvent(**defaults)


def _make_intent(**overrides: object) -> ParsedIntent:
    defaults: dict = {
        "intent": IntentType.CREATE,
        "title": "Park Picnic",
        "start_time": datetime(2026, 7, 12, 11, 0, tzinfo=UTC),
        "end_time": datetime(2026, 7, 12, 12, 0, tzinfo=UTC),
        "location": "Almaden Lake",
        "people": [FamilyMember(name="Dad", email="d@x.com", calendar_id="d@x.com")],
        "search_query": None,
        "raw_message": "picnic sunday at 11",
        "confidence": 0.92,
        "notes": None,
    }
    defaults.update(overrides)
    return ParsedIntent(**defaults)


def _build_test_app(
    calendar: AsyncMock | None = None,
    nlp: AsyncMock | None = None,
) -> web.Application:
    if calendar is None:
        calendar = AsyncMock()
        calendar.get_events.return_value = []
    if nlp is None:
        nlp = AsyncMock()
        nlp.parse_message.return_value = _make_intent()
    return build_app(calendar=calendar, nlp=nlp, calendar_ids=CALENDAR_IDS)


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {mint_token('rubotpaul')}"}


@pytest.fixture
def secret_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(SECRET_ENV_VAR, TEST_SECRET)


class TestHealthz:
    """Tests for the unauthenticated liveness probe."""

    @pytest.mark.asyncio
    async def test_healthz_ok_without_auth(self, secret_env: None) -> None:
        app = _build_test_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/healthz")
            assert resp.status == 200
            assert await resp.json() == {"ok": True}


class TestAuth:
    """Auth enforcement on /api/v1 routes."""

    @pytest.mark.asyncio
    async def test_list_events_requires_auth(self, secret_env: None) -> None:
        app = _build_test_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/v1/events")
            assert resp.status == 401

    @pytest.mark.asyncio
    async def test_parse_requires_auth(self, secret_env: None) -> None:
        app = _build_test_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.post("/api/v1/events/parse", json={"text": "hi"})
            assert resp.status == 401

    @pytest.mark.asyncio
    async def test_invalid_token_rejected(self, secret_env: None) -> None:
        app = _build_test_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.get(
                "/api/v1/events", headers={"Authorization": "Bearer garbage"}
            )
            assert resp.status == 401


class TestListEvents:
    """Tests for GET /api/v1/events."""

    @pytest.mark.asyncio
    async def test_happy_path_serializes_events(self, secret_env: None) -> None:
        calendar = AsyncMock()
        calendar.get_events.return_value = [_make_event()]
        app = _build_test_app(calendar=calendar)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/v1/events", headers=_auth_headers())
            assert resp.status == 200
            body = await resp.json()

        assert body["events"] == [
            {
                "id": "evt-1",
                "calendar_id": CALENDAR_IDS[0],
                "title": "Dentist Dash",
                "start": "2026-07-10T09:00:00+00:00",
                "end": "2026-07-10T10:00:00+00:00",
                "location": "123 Molar St",
                "attendees": ["Dad", "Layla"],
                "description": "Attendees: Dad, Layla",
            }
        ]

    @pytest.mark.asyncio
    async def test_happy_path_queries_configured_calendars(
        self, secret_env: None
    ) -> None:
        calendar = AsyncMock()
        calendar.get_events.return_value = []
        app = _build_test_app(calendar=calendar)
        start = "2026-07-10T00:00:00+00:00"
        end = "2026-07-11T00:00:00+00:00"
        async with TestClient(TestServer(app)) as client:
            resp = await client.get(
                "/api/v1/events",
                params={"from": start, "to": end},
                headers=_auth_headers(),
            )
            assert resp.status == 200
            body = await resp.json()

        assert body["from"] == start
        assert body["to"] == end
        calendar.get_events.assert_awaited_once_with(
            calendar_ids=CALENDAR_IDS,
            time_min=datetime.fromisoformat(start),
            time_max=datetime.fromisoformat(end),
        )

    @pytest.mark.asyncio
    async def test_defaults_to_seven_day_window(self, secret_env: None) -> None:
        calendar = AsyncMock()
        calendar.get_events.return_value = []
        app = _build_test_app(calendar=calendar)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/v1/events", headers=_auth_headers())
            assert resp.status == 200
            body = await resp.json()

        start = datetime.fromisoformat(body["from"])
        end = datetime.fromisoformat(body["to"])
        assert end - start == timedelta(days=7)
        assert start.tzinfo is not None

    @pytest.mark.asyncio
    async def test_window_over_60_days_rejected(self, secret_env: None) -> None:
        app = _build_test_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.get(
                "/api/v1/events",
                params={
                    "from": "2026-01-01T00:00:00+00:00",
                    "to": "2026-03-15T00:00:00+00:00",
                },
                headers=_auth_headers(),
            )
            assert resp.status == 400
            body = await resp.json()
        assert "60" in body["error"]

    @pytest.mark.asyncio
    async def test_window_at_exactly_60_days_allowed(self, secret_env: None) -> None:
        app = _build_test_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.get(
                "/api/v1/events",
                params={
                    "from": "2026-01-01T00:00:00+00:00",
                    "to": "2026-03-02T00:00:00+00:00",
                },
                headers=_auth_headers(),
            )
            assert resp.status == 200

    @pytest.mark.asyncio
    async def test_to_before_from_rejected(self, secret_env: None) -> None:
        app = _build_test_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.get(
                "/api/v1/events",
                params={
                    "from": "2026-07-10T00:00:00+00:00",
                    "to": "2026-07-09T00:00:00+00:00",
                },
                headers=_auth_headers(),
            )
            assert resp.status == 400

    @pytest.mark.asyncio
    async def test_malformed_datetime_rejected(self, secret_env: None) -> None:
        app = _build_test_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.get(
                "/api/v1/events",
                params={"from": "not-a-date"},
                headers=_auth_headers(),
            )
            assert resp.status == 400
            body = await resp.json()
        assert "from" in body["error"]

    @pytest.mark.asyncio
    async def test_naive_datetimes_treated_as_utc(self, secret_env: None) -> None:
        calendar = AsyncMock()
        calendar.get_events.return_value = []
        app = _build_test_app(calendar=calendar)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get(
                "/api/v1/events",
                params={
                    "from": "2026-07-10T00:00:00",
                    "to": "2026-07-11T00:00:00",
                },
                headers=_auth_headers(),
            )
            assert resp.status == 200

        call = calendar.get_events.await_args
        assert call.kwargs["time_min"].tzinfo is not None
        assert call.kwargs["time_max"].tzinfo is not None


class TestParseIntent:
    """Tests for POST /api/v1/events/parse."""

    @pytest.mark.asyncio
    async def test_happy_path_returns_intent_json(self, secret_env: None) -> None:
        nlp = AsyncMock()
        nlp.parse_message.return_value = _make_intent()
        app = _build_test_app(nlp=nlp)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/api/v1/events/parse",
                json={"text": "picnic sunday at 11"},
                headers=_auth_headers(),
            )
            assert resp.status == 200
            body = await resp.json()

        nlp.parse_message.assert_awaited_once_with("picnic sunday at 11")
        assert body == {
            "intent": "create",
            "confidence": 0.92,
            "fields": {
                "title": "Park Picnic",
                "start_time": "2026-07-12T11:00:00+00:00",
                "end_time": "2026-07-12T12:00:00+00:00",
                "location": "Almaden Lake",
                "people": ["Dad"],
                "search_query": None,
                "notes": None,
            },
        }

    @pytest.mark.asyncio
    async def test_none_fields_serialized_as_null(self, secret_env: None) -> None:
        nlp = AsyncMock()
        nlp.parse_message.return_value = _make_intent(
            intent=IntentType.QUERY,
            title=None,
            start_time=None,
            end_time=None,
            location=None,
            people=[],
        )
        app = _build_test_app(nlp=nlp)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/api/v1/events/parse",
                json={"text": "what's happening today"},
                headers=_auth_headers(),
            )
            body = await resp.json()

        assert body["intent"] == "query"
        assert body["fields"]["title"] is None
        assert body["fields"]["start_time"] is None
        assert body["fields"]["people"] == []

    @pytest.mark.asyncio
    async def test_empty_text_rejected(self, secret_env: None) -> None:
        app = _build_test_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/api/v1/events/parse",
                json={"text": "   "},
                headers=_auth_headers(),
            )
            assert resp.status == 400

    @pytest.mark.asyncio
    async def test_missing_text_rejected(self, secret_env: None) -> None:
        app = _build_test_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/api/v1/events/parse", json={}, headers=_auth_headers()
            )
            assert resp.status == 400

    @pytest.mark.asyncio
    async def test_non_string_text_rejected(self, secret_env: None) -> None:
        app = _build_test_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/api/v1/events/parse", json={"text": 42}, headers=_auth_headers()
            )
            assert resp.status == 400

    @pytest.mark.asyncio
    async def test_malformed_json_body_rejected(self, secret_env: None) -> None:
        app = _build_test_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/api/v1/events/parse",
                data="not json",
                headers={"Content-Type": "application/json", **_auth_headers()},
            )
            assert resp.status == 400

    @pytest.mark.asyncio
    async def test_non_object_json_body_rejected(self, secret_env: None) -> None:
        app = _build_test_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/api/v1/events/parse", json=["text"], headers=_auth_headers()
            )
            assert resp.status == 400
