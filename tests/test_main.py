"""Tests for schedule_minion.main module."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from discord.ext import commands

from schedule_minion.main import setup_bot


class TestSetupBot:
    """Tests for bot setup."""

    @pytest.mark.asyncio
    async def test_setup_bot_returns_bot_instance(self) -> None:
        env = {
            "DISCORD_TOKEN": "test-token",
            "DISCORD_CHANNEL_ID": "12345",
            "ANTHROPIC_API_KEY": "sk-test",
            "GOOGLE_CREDENTIALS_PATH": "creds/sa.json",
            "FAMILY_CALENDAR_ID": "family@group.calendar.google.com",
        }
        with patch.dict(os.environ, env, clear=False):
            bot = await setup_bot()

        assert isinstance(bot, commands.Bot)

    @pytest.mark.asyncio
    async def test_setup_bot_adds_scheduler_cog(self) -> None:
        env = {
            "DISCORD_TOKEN": "test-token",
            "DISCORD_CHANNEL_ID": "12345",
            "ANTHROPIC_API_KEY": "sk-test",
            "GOOGLE_CREDENTIALS_PATH": "creds/sa.json",
            "FAMILY_CALENDAR_ID": "family@group.calendar.google.com",
        }
        with patch.dict(os.environ, env, clear=False):
            bot = await setup_bot()

        cog = bot.cogs.get("SchedulerCog")
        assert cog is not None

    @pytest.mark.asyncio
    async def test_setup_bot_enables_message_content_intent(self) -> None:
        env = {
            "DISCORD_TOKEN": "test-token",
            "DISCORD_CHANNEL_ID": "12345",
            "ANTHROPIC_API_KEY": "sk-test",
            "GOOGLE_CREDENTIALS_PATH": "creds/sa.json",
            "FAMILY_CALENDAR_ID": "family@group.calendar.google.com",
        }
        with patch.dict(os.environ, env, clear=False):
            bot = await setup_bot()

        assert bot.intents.message_content is True
