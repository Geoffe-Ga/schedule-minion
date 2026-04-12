"""Configuration loaded from environment variables."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Settings:
    """Application settings loaded from environment variables."""

    discord_token: str
    discord_channel_id: int
    anthropic_api_key: str
    family_calendar_id: str
    google_credentials_path: str = ""
    google_credentials_info: dict[str, Any] | None = field(default=None, repr=False)
    timezone: str = "America/Los_Angeles"

    @classmethod
    def from_env(cls) -> Settings:
        """Create Settings from environment variables.

        Supports GOOGLE_CREDENTIALS_JSON as an alternative to
        GOOGLE_CREDENTIALS_PATH for platforms like Railway where
        credentials are passed as environment variables, not files.
        """
        google_creds_path = os.environ.get("GOOGLE_CREDENTIALS_PATH", "")
        google_creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON", "")
        google_creds_info: dict[str, Any] | None = None

        if google_creds_path:
            pass  # Use file path as-is
        elif google_creds_json:
            google_creds_info = json.loads(google_creds_json)
        else:
            msg = "Set GOOGLE_CREDENTIALS_PATH or GOOGLE_CREDENTIALS_JSON"
            raise KeyError(msg)

        return cls(
            discord_token=os.environ["DISCORD_TOKEN"],
            discord_channel_id=int(os.environ["DISCORD_CHANNEL_ID"]),
            anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
            google_credentials_path=google_creds_path,
            google_credentials_info=google_creds_info,
            family_calendar_id=os.environ["FAMILY_CALENDAR_ID"],
        )
