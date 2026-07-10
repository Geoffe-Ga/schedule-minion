"""Tests for schedule_minion.config module."""

from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest

from schedule_minion.auth_middleware import SECRET_ENV_VAR
from schedule_minion.config import (
    API_PORT_ENV_VAR,
    DEFAULT_API_HOST,
    DEFAULT_API_PORT,
    ApiSettings,
)

BASE_ENV = {
    "ANTHROPIC_API_KEY": "sk-test-key",
    "FAMILY_CALENDAR_ID": "family@group.calendar.google.com",
    "GOOGLE_CREDENTIALS_PATH": "creds/sa.json",
    SECRET_ENV_VAR: "test-shared-secret",
}


class TestApiSettings:
    """Tests for ApiSettings configuration."""

    def test_from_env_loads_all_required_fields(self) -> None:
        with patch.dict(os.environ, BASE_ENV, clear=True):
            settings = ApiSettings.from_env()

        assert settings.anthropic_api_key == "sk-test-key"
        assert settings.family_calendar_id == "family@group.calendar.google.com"
        assert settings.google_credentials_path == "creds/sa.json"
        assert settings.google_credentials_info is None

    def test_from_env_defaults(self) -> None:
        with patch.dict(os.environ, BASE_ENV, clear=True):
            settings = ApiSettings.from_env()

        assert settings.timezone == "America/Los_Angeles"
        assert settings.host == DEFAULT_API_HOST == "127.0.0.1"
        assert settings.port == DEFAULT_API_PORT == 8003

    def test_from_env_custom_port(self) -> None:
        env = {**BASE_ENV, API_PORT_ENV_VAR: "9010"}
        with patch.dict(os.environ, env, clear=True):
            assert ApiSettings.from_env().port == 9010

    def test_from_env_missing_vars_lists_all(self) -> None:
        with (
            patch.dict(os.environ, {}, clear=True),
            pytest.raises(RuntimeError) as excinfo,
        ):
            ApiSettings.from_env()

        message = str(excinfo.value)
        assert "ANTHROPIC_API_KEY" in message
        assert "FAMILY_CALENDAR_ID" in message
        assert SECRET_ENV_VAR in message
        assert "GOOGLE_CREDENTIALS" in message

    def test_from_env_missing_google_credentials_only(self) -> None:
        env = {k: v for k, v in BASE_ENV.items() if k != "GOOGLE_CREDENTIALS_PATH"}
        with (
            patch.dict(os.environ, env, clear=True),
            pytest.raises(RuntimeError, match="GOOGLE_CREDENTIALS"),
        ):
            ApiSettings.from_env()

    def test_from_env_non_integer_port(self) -> None:
        env = {**BASE_ENV, API_PORT_ENV_VAR: "eight-thousand"}
        with (
            patch.dict(os.environ, env, clear=True),
            pytest.raises(ValueError, match=API_PORT_ENV_VAR),
        ):
            ApiSettings.from_env()

    @pytest.mark.parametrize("port", [0, -1, 65536])
    def test_port_out_of_range(self, port: int) -> None:
        with pytest.raises(ValueError, match="port"):
            ApiSettings(
                anthropic_api_key="k",
                family_calendar_id="c",
                google_credentials_path="p",
                port=port,
            )

    def test_frozen_dataclass(self) -> None:
        with patch.dict(os.environ, BASE_ENV, clear=True):
            settings = ApiSettings.from_env()

        with pytest.raises(AttributeError):
            settings.anthropic_api_key = "new-value"  # type: ignore[misc]

    def test_google_credentials_json_stores_info_dict(self) -> None:
        creds = {"type": "service_account", "project_id": "test"}
        env = {k: v for k, v in BASE_ENV.items() if k != "GOOGLE_CREDENTIALS_PATH"}
        env["GOOGLE_CREDENTIALS_JSON"] = json.dumps(creds)
        with patch.dict(os.environ, env, clear=True):
            settings = ApiSettings.from_env()

        assert settings.google_credentials_info == creds
        assert settings.google_credentials_path == ""

    def test_credentials_path_takes_precedence_over_json(self) -> None:
        env = {**BASE_ENV, "GOOGLE_CREDENTIALS_JSON": '{"should": "be ignored"}'}
        with patch.dict(os.environ, env, clear=True):
            settings = ApiSettings.from_env()

        assert settings.google_credentials_path == "creds/sa.json"
        assert settings.google_credentials_info is None
