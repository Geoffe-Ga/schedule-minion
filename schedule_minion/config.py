"""Configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """Application settings loaded from environment variables."""

    discord_token: str
    discord_channel_id: int
    anthropic_api_key: str
    google_credentials_path: str
    family_calendar_id: str
    timezone: str = "America/Los_Angeles"

    @classmethod
    def from_env(cls) -> Settings:
        """Create Settings from environment variables."""
        return cls(
            discord_token=os.environ["DISCORD_TOKEN"],
            discord_channel_id=int(os.environ["DISCORD_CHANNEL_ID"]),
            anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
            google_credentials_path=os.environ["GOOGLE_CREDENTIALS_PATH"],
            family_calendar_id=os.environ["FAMILY_CALENDAR_ID"],
        )
