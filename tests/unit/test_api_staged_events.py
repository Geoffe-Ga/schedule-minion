"""Tests for the staged destructive event endpoints in schedule_minion.api.

Covers the draft -> confirm -> execute contract: staging performs no
calendar write, conflicts are checked before staging, and a staged action
is applied exactly once via the mocked ``CalendarService``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest
from aiohttp.test_utils import TestClient, TestServer

from schedule_minion.api import build_app
from schedule_minion.auth_middleware import SECRET_ENV_VAR, mint_token
from schedule_minion.models.events import CalendarEvent

if TYPE_CHECKING:
    from aiohttp import web

TEST_SECRET = "test-shared-secret"
CALENDAR_IDS = ["family@example.com", "geoff@example.com"]

CREATE_BODY = {
    "title": "Park Picnic",
    "start": "2026-07-12T11:00:00+00:00",
    "end": "2026-07-12T12:00:00+00:00",
    "location": "Almaden Lake",
}

RESCHEDULE_BODY = {
    "event_id": "evt-1",
    "new_start": "2026-07-13T09:00:00+00:00",
    "new_end": "2026-07-13T10:00:00+00:00",
}


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


def _make_calendar() -> AsyncMock:
    """A CalendarService mock with quiet defaults for the staged flow."""
    calendar = AsyncMock()
    calendar.find_conflicts.return_value = []
    calendar.get_event.return_value = _make_event()
    calendar.create_event.return_value = _make_event(
        event_id="evt-new", title="Park Picnic"
    )
    calendar.update_event.return_value = _make_event(
        start_time=datetime(2026, 7, 13, 9, 0, tzinfo=UTC),
        end_time=datetime(2026, 7, 13, 10, 0, tzinfo=UTC),
    )
    calendar.delete_event.return_value = True
    return calendar


def _build_test_app(calendar: AsyncMock | None = None) -> web.Application:
    if calendar is None:
        calendar = _make_calendar()
    return build_app(calendar=calendar, nlp=AsyncMock(), calendar_ids=CALENDAR_IDS)


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {mint_token('rubotpaul')}"}


@pytest.fixture
def secret_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(SECRET_ENV_VAR, TEST_SECRET)


async def _stage_create(
    client: TestClient, body: dict | None = None
) -> tuple[int, dict]:
    resp = await client.post(
        "/api/v1/events/create", json=body or CREATE_BODY, headers=_auth_headers()
    )
    return resp.status, await resp.json()


async def _confirm(client: TestClient, action_id: object) -> tuple[int, dict]:
    resp = await client.post(
        "/api/v1/events/confirm",
        json={"action_id": action_id},
        headers=_auth_headers(),
    )
    return resp.status, await resp.json()


class TestAuthRequired:
    """All staged endpoints reject requests without a bearer token."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("POST", "/api/v1/events/create"),
            ("POST", "/api/v1/events/reschedule"),
            ("DELETE", "/api/v1/events/evt-1"),
            ("POST", "/api/v1/events/confirm"),
        ],
    )
    async def test_401_without_bearer(
        self, secret_env: None, method: str, path: str
    ) -> None:
        app = _build_test_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.request(method, path, json={})
            assert resp.status == 401


class TestCreateStaging:
    """Tests for POST /api/v1/events/create."""

    @pytest.mark.asyncio
    async def test_returns_pending_and_writes_nothing(self, secret_env: None) -> None:
        calendar = _make_calendar()
        app = _build_test_app(calendar)
        async with TestClient(TestServer(app)) as client:
            status, body = await _stage_create(client)

        assert status == 200
        assert body["status"] == "pending_confirmation"
        assert body["action_id"]
        assert body["expires_in"] == 300
        assert body["preview"]["title"] == "Park Picnic"
        calendar.create_event.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_conflict_returns_409_and_stages_nothing(
        self, secret_env: None
    ) -> None:
        calendar = _make_calendar()
        calendar.find_conflicts.return_value = [_make_event()]
        app = _build_test_app(calendar)
        async with TestClient(TestServer(app)) as client:
            status, body = await _stage_create(client)

        assert status == 409
        assert body["error"] == "conflict"
        assert [c["id"] for c in body["conflicts"]] == ["evt-1"]
        assert "action_id" not in body
        calendar.create_event.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_conflict_check_runs_before_staging(self, secret_env: None) -> None:
        calendar = _make_calendar()
        app = _build_test_app(calendar)
        async with TestClient(TestServer(app)) as client:
            status, _ = await _stage_create(client)

        assert status == 200
        calendar.find_conflicts.assert_awaited_once_with(
            calendar_ids=CALENDAR_IDS,
            start_time=datetime(2026, 7, 12, 11, 0, tzinfo=UTC),
            end_time=datetime(2026, 7, 12, 12, 0, tzinfo=UTC),
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("missing", ["title", "start", "end"])
    async def test_missing_required_field_rejected(
        self, secret_env: None, missing: str
    ) -> None:
        body = {k: v for k, v in CREATE_BODY.items() if k != missing}
        app = _build_test_app()
        async with TestClient(TestServer(app)) as client:
            status, payload = await _stage_create(client, body)

        assert status == 400
        assert missing in payload["error"]

    @pytest.mark.asyncio
    async def test_malformed_datetime_rejected(self, secret_env: None) -> None:
        app = _build_test_app()
        async with TestClient(TestServer(app)) as client:
            status, _ = await _stage_create(
                client, {**CREATE_BODY, "start": "next tuesday"}
            )
        assert status == 400

    @pytest.mark.asyncio
    async def test_end_not_after_start_rejected(self, secret_env: None) -> None:
        app = _build_test_app()
        async with TestClient(TestServer(app)) as client:
            status, _ = await _stage_create(
                client, {**CREATE_BODY, "end": CREATE_BODY["start"]}
            )
        assert status == 400

    @pytest.mark.asyncio
    async def test_unknown_calendar_id_rejected(self, secret_env: None) -> None:
        app = _build_test_app()
        async with TestClient(TestServer(app)) as client:
            status, _ = await _stage_create(
                client, {**CREATE_BODY, "calendar_id": "stranger@example.com"}
            )
        assert status == 400

    @pytest.mark.asyncio
    async def test_naive_datetimes_treated_as_utc(self, secret_env: None) -> None:
        calendar = _make_calendar()
        app = _build_test_app(calendar)
        async with TestClient(TestServer(app)) as client:
            status, _ = await _stage_create(
                client,
                {
                    **CREATE_BODY,
                    "start": "2026-07-12T11:00:00",
                    "end": "2026-07-12T12:00:00",
                },
            )

        assert status == 200
        call = calendar.find_conflicts.await_args
        assert call.kwargs["start_time"].tzinfo is not None
        assert call.kwargs["end_time"].tzinfo is not None

    @pytest.mark.asyncio
    async def test_malformed_json_rejected(self, secret_env: None) -> None:
        app = _build_test_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/api/v1/events/create",
                data="not json",
                headers={"Content-Type": "application/json", **_auth_headers()},
            )
            assert resp.status == 400

    @pytest.mark.asyncio
    async def test_non_object_json_rejected(self, secret_env: None) -> None:
        app = _build_test_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/api/v1/events/create", json=["nope"], headers=_auth_headers()
            )
            assert resp.status == 400


class TestRescheduleStaging:
    """Tests for POST /api/v1/events/reschedule."""

    @pytest.mark.asyncio
    async def test_returns_pending_and_writes_nothing(self, secret_env: None) -> None:
        calendar = _make_calendar()
        app = _build_test_app(calendar)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/api/v1/events/reschedule",
                json=RESCHEDULE_BODY,
                headers=_auth_headers(),
            )
            assert resp.status == 200
            body = await resp.json()

        assert body["status"] == "pending_confirmation"
        assert body["preview"]["title"] == "Dentist Dash"
        calendar.get_event.assert_awaited_once_with(
            calendar_ids=CALENDAR_IDS, event_id="evt-1"
        )
        calendar.update_event.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("missing", ["event_id", "new_start", "new_end"])
    async def test_missing_required_field_rejected(
        self, secret_env: None, missing: str
    ) -> None:
        body = {k: v for k, v in RESCHEDULE_BODY.items() if k != missing}
        app = _build_test_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/api/v1/events/reschedule", json=body, headers=_auth_headers()
            )
            assert resp.status == 400
            payload = await resp.json()
        assert missing in payload["error"]

    @pytest.mark.asyncio
    async def test_unknown_event_rejected(self, secret_env: None) -> None:
        calendar = _make_calendar()
        calendar.get_event.side_effect = KeyError("evt-1")
        app = _build_test_app(calendar)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/api/v1/events/reschedule",
                json=RESCHEDULE_BODY,
                headers=_auth_headers(),
            )
            assert resp.status == 404


class TestDeleteStaging:
    """Tests for DELETE /api/v1/events/{event_id}."""

    @pytest.mark.asyncio
    async def test_returns_pending_with_title_and_writes_nothing(
        self, secret_env: None
    ) -> None:
        calendar = _make_calendar()
        app = _build_test_app(calendar)
        async with TestClient(TestServer(app)) as client:
            resp = await client.delete("/api/v1/events/evt-1", headers=_auth_headers())
            assert resp.status == 200
            body = await resp.json()

        assert body["status"] == "pending_confirmation"
        assert body["preview"]["title"] == "Dentist Dash"
        calendar.delete_event.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unknown_event_returns_404(self, secret_env: None) -> None:
        calendar = _make_calendar()
        calendar.get_event.side_effect = KeyError("evt-404")
        app = _build_test_app(calendar)
        async with TestClient(TestServer(app)) as client:
            resp = await client.delete(
                "/api/v1/events/evt-404", headers=_auth_headers()
            )
            assert resp.status == 404


class TestConfirm:
    """Tests for POST /api/v1/events/confirm."""

    @pytest.mark.asyncio
    async def test_confirm_applies_create(self, secret_env: None) -> None:
        calendar = _make_calendar()
        app = _build_test_app(calendar)
        async with TestClient(TestServer(app)) as client:
            _, staged = await _stage_create(client)
            status, body = await _confirm(client, staged["action_id"])

        assert status == 200
        assert body["status"] == "confirmed"
        assert body["result"]["id"] == "evt-new"
        calendar.create_event.assert_awaited_once_with(
            calendar_id=CALENDAR_IDS[0],
            title="Park Picnic",
            start_time=datetime(2026, 7, 12, 11, 0, tzinfo=UTC),
            end_time=datetime(2026, 7, 12, 12, 0, tzinfo=UTC),
            location="Almaden Lake",
        )

    @pytest.mark.asyncio
    async def test_confirm_applies_reschedule(self, secret_env: None) -> None:
        calendar = _make_calendar()
        app = _build_test_app(calendar)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/api/v1/events/reschedule",
                json=RESCHEDULE_BODY,
                headers=_auth_headers(),
            )
            staged = await resp.json()
            status, body = await _confirm(client, staged["action_id"])

        assert status == 200
        assert body["status"] == "confirmed"
        calendar.update_event.assert_awaited_once_with(
            calendar_id=CALENDAR_IDS[0],
            event_id="evt-1",
            start_time=datetime(2026, 7, 13, 9, 0, tzinfo=UTC),
            end_time=datetime(2026, 7, 13, 10, 0, tzinfo=UTC),
        )

    @pytest.mark.asyncio
    async def test_confirm_applies_delete(self, secret_env: None) -> None:
        calendar = _make_calendar()
        app = _build_test_app(calendar)
        async with TestClient(TestServer(app)) as client:
            resp = await client.delete("/api/v1/events/evt-1", headers=_auth_headers())
            staged = await resp.json()
            status, body = await _confirm(client, staged["action_id"])

        assert status == 200
        assert body["result"] == {"deleted": "evt-1", "title": "Dentist Dash"}
        calendar.delete_event.assert_awaited_once_with(
            calendar_id=CALENDAR_IDS[0], event_id="evt-1"
        )

    @pytest.mark.asyncio
    async def test_unknown_action_id_returns_404(self, secret_env: None) -> None:
        app = _build_test_app()
        async with TestClient(TestServer(app)) as client:
            status, _ = await _confirm(client, "no-such-action")
        assert status == 404

    @pytest.mark.asyncio
    async def test_missing_action_id_rejected(self, secret_env: None) -> None:
        app = _build_test_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/api/v1/events/confirm", json={}, headers=_auth_headers()
            )
            assert resp.status == 400

    @pytest.mark.asyncio
    async def test_non_string_action_id_rejected(self, secret_env: None) -> None:
        app = _build_test_app()
        async with TestClient(TestServer(app)) as client:
            status, _ = await _confirm(client, 42)
        assert status == 400

    @pytest.mark.asyncio
    async def test_expired_action_returns_410(
        self, secret_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("schedule_minion.api.PENDING_TTL_SECONDS", -1)
        calendar = _make_calendar()
        app = _build_test_app(calendar)
        async with TestClient(TestServer(app)) as client:
            _, staged = await _stage_create(client)
            status, _ = await _confirm(client, staged["action_id"])

        assert status == 410
        calendar.create_event.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_confirm_after_expiry_returns_409(
        self, secret_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("schedule_minion.api.PENDING_TTL_SECONDS", -1)
        app = _build_test_app()
        async with TestClient(TestServer(app)) as client:
            _, staged = await _stage_create(client)
            first, _ = await _confirm(client, staged["action_id"])
            second, _ = await _confirm(client, staged["action_id"])

        assert first == 410
        assert second == 409

    @pytest.mark.asyncio
    async def test_double_confirm_returns_409(self, secret_env: None) -> None:
        calendar = _make_calendar()
        app = _build_test_app(calendar)
        async with TestClient(TestServer(app)) as client:
            _, staged = await _stage_create(client)
            first, _ = await _confirm(client, staged["action_id"])
            second, _ = await _confirm(client, staged["action_id"])

        assert first == 200
        assert second == 409
        calendar.create_event.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_failed_delete_returns_502_and_allows_retry(
        self, secret_env: None
    ) -> None:
        calendar = _make_calendar()
        calendar.delete_event.side_effect = [False, True]
        app = _build_test_app(calendar)
        async with TestClient(TestServer(app)) as client:
            resp = await client.delete("/api/v1/events/evt-1", headers=_auth_headers())
            staged = await resp.json()
            first, _ = await _confirm(client, staged["action_id"])
            second, body = await _confirm(client, staged["action_id"])

        assert first == 502
        assert second == 200
        assert body["status"] == "confirmed"
