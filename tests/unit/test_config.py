"""Tests for schedule_minion.config module."""

from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest

from schedule_minion.config import Settings, _write_credentials_file


class TestSettings:
    """Tests for Settings configuration."""

    def test_from_env_loads_all_required_fields(self) -> None:
        env = {
            "DISCORD_TOKEN": "test-token",
            "DISCORD_CHANNEL_ID": "123456",
            "ANTHROPIC_API_KEY": "sk-test-key",
            "GOOGLE_CREDENTIALS_PATH": "creds/sa.json",
            "FAMILY_CALENDAR_ID": "family@group.calendar.google.com",
        }
        with patch.dict(os.environ, env, clear=False):
            settings = Settings.from_env()

        assert settings.discord_token == "test-token"
        assert settings.discord_channel_id == 123456
        assert settings.anthropic_api_key == "sk-test-key"
        assert settings.google_credentials_path == "creds/sa.json"
        assert settings.family_calendar_id == "family@group.calendar.google.com"

    def test_default_timezone(self) -> None:
        env = {
            "DISCORD_TOKEN": "t",
            "DISCORD_CHANNEL_ID": "1",
            "ANTHROPIC_API_KEY": "k",
            "GOOGLE_CREDENTIALS_PATH": "p",
            "FAMILY_CALENDAR_ID": "c",
        }
        with patch.dict(os.environ, env, clear=False):
            settings = Settings.from_env()

        assert settings.timezone == "America/Los_Angeles"

    def test_missing_env_var_raises(self) -> None:
        with patch.dict(os.environ, {}, clear=True), pytest.raises(KeyError):
            Settings.from_env()

    def test_frozen_dataclass(self) -> None:
        env = {
            "DISCORD_TOKEN": "t",
            "DISCORD_CHANNEL_ID": "1",
            "ANTHROPIC_API_KEY": "k",
            "GOOGLE_CREDENTIALS_PATH": "p",
            "FAMILY_CALENDAR_ID": "c",
        }
        with patch.dict(os.environ, env, clear=False):
            settings = Settings.from_env()

        with pytest.raises(AttributeError):
            settings.discord_token = "new-value"  # type: ignore[misc]

    def test_google_credentials_json_creates_temp_file(self) -> None:
        creds = {"type": "service_account", "project_id": "test"}
        env = {
            "DISCORD_TOKEN": "t",
            "DISCORD_CHANNEL_ID": "1",
            "ANTHROPIC_API_KEY": "k",
            "GOOGLE_CREDENTIALS_JSON": json.dumps(creds),
            "FAMILY_CALENDAR_ID": "c",
        }
        with patch.dict(os.environ, env, clear=False):
            settings = Settings.from_env()

        assert settings.google_credentials_path.endswith(".json")
        with open(settings.google_credentials_path) as f:
            assert json.load(f) == creds

    def test_credentials_path_takes_precedence_over_json(self) -> None:
        env = {
            "DISCORD_TOKEN": "t",
            "DISCORD_CHANNEL_ID": "1",
            "ANTHROPIC_API_KEY": "k",
            "GOOGLE_CREDENTIALS_PATH": "explicit/path.json",
            "GOOGLE_CREDENTIALS_JSON": '{"should": "be ignored"}',
            "FAMILY_CALENDAR_ID": "c",
        }
        with patch.dict(os.environ, env, clear=False):
            settings = Settings.from_env()

        assert settings.google_credentials_path == "explicit/path.json"

    def test_no_credentials_raises(self) -> None:
        env = {
            "DISCORD_TOKEN": "t",
            "DISCORD_CHANNEL_ID": "1",
            "ANTHROPIC_API_KEY": "k",
            "FAMILY_CALENDAR_ID": "c",
        }
        with (
            patch.dict(os.environ, env, clear=False),
            pytest.raises(KeyError, match="GOOGLE_CREDENTIALS"),
        ):
            Settings.from_env()


class TestWriteCredentialsFile:
    """Tests for _write_credentials_file helper."""

    def test_writes_valid_json(self) -> None:
        creds = {"type": "service_account", "key": "value"}
        path = _write_credentials_file(json.dumps(creds))
        with open(path) as f:
            assert json.load(f) == creds

    def test_returns_json_suffix(self) -> None:
        path = _write_credentials_file('{"a": 1}')
        assert path.endswith(".json")
