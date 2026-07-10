"""Tests for schedule_minion.auth_middleware module."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from schedule_minion.auth_middleware import (
    MAX_TOKEN_AGE_SECONDS,
    MAX_TOKEN_FUTURE_SKEW_SECONDS,
    SECRET_ENV_VAR,
    AuthError,
    _verify_token,
    aiohttp_auth_middleware,
    mint_token,
)

TEST_SECRET = "test-shared-secret"
SECRET_ENV = {SECRET_ENV_VAR: TEST_SECRET}


class TestMintAndVerifyToken:
    """Tests for mint_token and _verify_token."""

    def test_valid_token_round_trip(self) -> None:
        with patch.dict(os.environ, SECRET_ENV, clear=False):
            token = mint_token("rubotpaul")
            assert _verify_token(token) == "rubotpaul"

    def test_valid_token_round_trip_with_explicit_now(self) -> None:
        with patch.dict(os.environ, SECRET_ENV, clear=False):
            token = mint_token("rubotpaul", now=1_000_000.0)
            assert _verify_token(token, now=1_000_000.0) == "rubotpaul"

    def test_token_format(self) -> None:
        with patch.dict(os.environ, SECRET_ENV, clear=False):
            token = mint_token("rubotpaul", now=1_000_000.0)

        caller_id, ts, sig = token.split(".")
        assert caller_id == "rubotpaul"
        assert ts == "1000000"
        assert len(sig) == 64  # hex-encoded SHA-256

    def test_expired_token_rejected(self) -> None:
        with patch.dict(os.environ, SECRET_ENV, clear=False):
            minted_at = 1_000_000.0
            token = mint_token("rubotpaul", now=minted_at)
            expired_at = minted_at + MAX_TOKEN_AGE_SECONDS + 1

            with pytest.raises(AuthError, match="token expired"):
                _verify_token(token, now=expired_at)

    def test_token_at_max_age_still_valid(self) -> None:
        with patch.dict(os.environ, SECRET_ENV, clear=False):
            minted_at = 1_000_000.0
            token = mint_token("rubotpaul", now=minted_at)
            boundary = minted_at + MAX_TOKEN_AGE_SECONDS

            assert _verify_token(token, now=boundary) == "rubotpaul"

    def test_future_token_beyond_skew_rejected(self) -> None:
        with patch.dict(os.environ, SECRET_ENV, clear=False):
            now = 1_000_000.0
            minted_at = now + MAX_TOKEN_FUTURE_SKEW_SECONDS + 1
            token = mint_token("rubotpaul", now=minted_at)

            with pytest.raises(AuthError, match="token from future"):
                _verify_token(token, now=now)

    def test_future_token_within_skew_accepted(self) -> None:
        with patch.dict(os.environ, SECRET_ENV, clear=False):
            now = 1_000_000.0
            minted_at = now + MAX_TOKEN_FUTURE_SKEW_SECONDS
            token = mint_token("rubotpaul", now=minted_at)

            assert _verify_token(token, now=now) == "rubotpaul"

    def test_malformed_token_rejected(self) -> None:
        with (
            patch.dict(os.environ, SECRET_ENV, clear=False),
            pytest.raises(AuthError, match="malformed token"),
        ):
            _verify_token("not-a-token")

    def test_token_with_too_many_parts_rejected(self) -> None:
        with (
            patch.dict(os.environ, SECRET_ENV, clear=False),
            pytest.raises(AuthError, match="malformed token"),
        ):
            _verify_token("a.b.c.d")

    def test_malformed_timestamp_rejected(self) -> None:
        with (
            patch.dict(os.environ, SECRET_ENV, clear=False),
            pytest.raises(AuthError, match="malformed timestamp"),
        ):
            _verify_token("rubotpaul.not-a-number.deadbeef")

    def test_bad_signature_rejected(self) -> None:
        with patch.dict(os.environ, SECRET_ENV, clear=False):
            token = mint_token("rubotpaul", now=1_000_000.0)
            caller_id, ts, _sig = token.split(".")
            tampered = f"{caller_id}.{ts}.{'0' * 64}"

            with pytest.raises(AuthError, match="bad signature"):
                _verify_token(tampered, now=1_000_000.0)

    def test_token_signed_with_wrong_secret_rejected(self) -> None:
        with patch.dict(os.environ, {SECRET_ENV_VAR: "other"}, clear=False):
            token = mint_token("rubotpaul", now=1_000_000.0)
        with (
            patch.dict(os.environ, SECRET_ENV, clear=False),
            pytest.raises(AuthError, match="bad signature"),
        ):
            _verify_token(token, now=1_000_000.0)

    def test_missing_secret_raises_runtime_error_on_mint(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != SECRET_ENV_VAR}
        with (
            patch.dict(os.environ, env, clear=True),
            pytest.raises(RuntimeError, match=SECRET_ENV_VAR),
        ):
            mint_token("rubotpaul")

    def test_missing_secret_raises_runtime_error_on_verify(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != SECRET_ENV_VAR}
        with (
            patch.dict(os.environ, env, clear=True),
            pytest.raises(RuntimeError, match=SECRET_ENV_VAR),
        ):
            _verify_token("rubotpaul.1000000.deadbeef", now=1_000_000.0)

    def test_auth_error_carries_reason_and_status(self) -> None:
        error = AuthError("bad signature")
        assert error.reason == "bad signature"
        assert error.status == 401


class TestAiohttpAuthMiddleware:
    """Tests for the aiohttp middleware factory."""

    @staticmethod
    async def _ok_handler(request: web.Request) -> web.StreamResponse:
        return web.json_response({"caller_id": request["caller_id"]})

    async def _invoke(self, authorization: str | None) -> web.StreamResponse:
        headers = {} if authorization is None else {"Authorization": authorization}
        request = make_mocked_request("GET", "/api/v1/events", headers=headers)
        middleware = await aiohttp_auth_middleware(web.Application(), self._ok_handler)
        return await middleware(request)

    @pytest.mark.asyncio
    async def test_valid_token_reaches_handler(self) -> None:
        with patch.dict(os.environ, SECRET_ENV, clear=False):
            token = mint_token("rubotpaul")
            response = await self._invoke(f"Bearer {token}")

        assert response.status == 200

    @pytest.mark.asyncio
    async def test_valid_token_sets_caller_id_on_request(self) -> None:
        with patch.dict(os.environ, SECRET_ENV, clear=False):
            token = mint_token("rubotpaul")
            request = make_mocked_request(
                "GET", "/api/v1/events", headers={"Authorization": f"Bearer {token}"}
            )
            middleware = await aiohttp_auth_middleware(
                web.Application(), self._ok_handler
            )
            await middleware(request)

        assert request["caller_id"] == "rubotpaul"

    @pytest.mark.asyncio
    async def test_missing_header_returns_401(self) -> None:
        with patch.dict(os.environ, SECRET_ENV, clear=False):
            response = await self._invoke(None)

        assert response.status == 401

    @pytest.mark.asyncio
    async def test_non_bearer_header_returns_401(self) -> None:
        with patch.dict(os.environ, SECRET_ENV, clear=False):
            response = await self._invoke("Basic dXNlcjpwYXNz")

        assert response.status == 401

    @pytest.mark.asyncio
    async def test_invalid_token_returns_401(self) -> None:
        with patch.dict(os.environ, SECRET_ENV, clear=False):
            response = await self._invoke("Bearer garbage")

        assert response.status == 401

    @pytest.mark.asyncio
    async def test_expired_token_returns_401(self) -> None:
        with patch.dict(os.environ, SECRET_ENV, clear=False):
            stale = mint_token("rubotpaul", now=0.0)
            response = await self._invoke(f"Bearer {stale}")

        assert response.status == 401
