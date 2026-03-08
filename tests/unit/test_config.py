"""Tests for schedule_minion.config module."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from schedule_minion.config import Settings


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
