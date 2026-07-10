"""Tests for the standalone API entrypoint (``python -m schedule_minion.api``)."""

from __future__ import annotations

import asyncio
import os
import signal
import socket
from typing import Any
from unittest.mock import patch

import aiohttp
import pytest

from schedule_minion.api import main, serve
from schedule_minion.auth_middleware import SECRET_ENV_VAR
from schedule_minion.config import API_PORT_ENV_VAR, ApiSettings

TEST_SECRET = "test-shared-secret"


@pytest.fixture(autouse=True)
def api_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provide the standalone API's required environment variables."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    monkeypatch.setenv("FAMILY_CALENDAR_ID", "family@group.calendar.google.com")
    monkeypatch.setenv("GOOGLE_CREDENTIALS_PATH", "creds/sa.json")
    monkeypatch.setenv(SECRET_ENV_VAR, TEST_SECRET)
    monkeypatch.delenv(API_PORT_ENV_VAR, raising=False)


def _free_port() -> int:
    """Reserve an ephemeral localhost port for a test server."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _settings(port: int) -> ApiSettings:
    """Build ApiSettings bound to localhost on the given port."""
    return ApiSettings(
        anthropic_api_key="sk-test-key",
        family_calendar_id="family@group.calendar.google.com",
        google_credentials_path="creds/sa.json",
        port=port,
    )


async def _wait_for_healthz(port: int) -> dict[str, Any]:
    """Poll /healthz until the API responds, returning its JSON body."""
    async with aiohttp.ClientSession() as session:
        for _ in range(50):
            try:
                url = f"http://127.0.0.1:{port}/healthz"
                async with session.get(url) as resp:
                    if resp.status == 200:
                        body: dict[str, Any] = await resp.json()
                        return body
            except aiohttp.ClientConnectionError:
                await asyncio.sleep(0.1)
    raise AssertionError("healthz never responded")


async def _healthz_refused(port: int) -> bool:
    """Report whether /healthz now refuses connections."""
    async with aiohttp.ClientSession() as session:
        try:
            url = f"http://127.0.0.1:{port}/healthz"
            async with session.get(url):
                return False
        except aiohttp.ClientConnectionError:
            return True


class TestServe:
    """Tests for the serve coroutine."""

    @pytest.mark.asyncio
    async def test_serve_boots_and_healthz_responds(self) -> None:
        """serve() boots a real server whose /healthz answers, then stops."""
        port = _free_port()
        stop = asyncio.Event()
        task = asyncio.create_task(serve(_settings(port), stop=stop))

        try:
            assert await _wait_for_healthz(port) == {"ok": True}
        finally:
            stop.set()
            await asyncio.wait_for(task, timeout=5)

        assert await _healthz_refused(port)

    @pytest.mark.asyncio
    async def test_serve_requires_auth_on_api_routes(self) -> None:
        """The served /api/v1 routes reject unauthenticated requests."""
        port = _free_port()
        stop = asyncio.Event()
        task = asyncio.create_task(serve(_settings(port), stop=stop))

        try:
            await _wait_for_healthz(port)
            async with (
                aiohttp.ClientSession() as session,
                session.get(f"http://127.0.0.1:{port}/api/v1/events") as resp,
            ):
                assert resp.status == 401
        finally:
            stop.set()
            await asyncio.wait_for(task, timeout=5)

    @pytest.mark.asyncio
    async def test_serve_sigterm_triggers_graceful_shutdown(self) -> None:
        """SIGTERM stops the server and cleans up the runner."""
        port = _free_port()
        task = asyncio.create_task(serve(_settings(port)))

        await _wait_for_healthz(port)
        os.kill(os.getpid(), signal.SIGTERM)
        await asyncio.wait_for(task, timeout=5)

        assert await _healthz_refused(port)


class TestMain:
    """Tests for the synchronous main() wrapper."""

    def test_main_serves_settings_from_env(self) -> None:
        """main() loads .env, builds settings from env, and runs serve()."""
        captured: dict[str, Any] = {}

        async def fake_serve(settings: ApiSettings) -> None:
            captured["settings"] = settings

        with (
            patch("schedule_minion.api.load_dotenv") as load_dotenv,
            patch("schedule_minion.api.serve", fake_serve),
        ):
            main()

        load_dotenv.assert_called_once_with()
        assert captured["settings"] == ApiSettings.from_env()
