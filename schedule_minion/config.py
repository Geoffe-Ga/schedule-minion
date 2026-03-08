"""Configuration loaded from environment variables."""

from __future__ import annotations

import json
import os
import tempfile
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
        """Create Settings from environment variables.

        Supports GOOGLE_CREDENTIALS_JSON as an alternative to
        GOOGLE_CREDENTIALS_PATH for platforms like Railway where
        credentials are passed as environment variables, not files.
        """
        google_creds_path = os.environ.get("GOOGLE_CREDENTIALS_PATH", "")
        google_creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON", "")

        if not google_creds_path and google_creds_json:
            google_creds_path = _write_credentials_file(google_creds_json)
        elif not google_creds_path:
            msg = "Set GOOGLE_CREDENTIALS_PATH or GOOGLE_CREDENTIALS_JSON"
            raise KeyError(msg)

        return cls(
            discord_token=os.environ["DISCORD_TOKEN"],
            discord_channel_id=int(os.environ["DISCORD_CHANNEL_ID"]),
            anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
            google_credentials_path=google_creds_path,
            family_calendar_id=os.environ["FAMILY_CALENDAR_ID"],
        )


def _write_credentials_file(creds_json: str) -> str:
    """Write a Google credentials JSON string to a temp file.

    Returns the path to the temp file. The file persists for the
    lifetime of the process (delete=False).
    """
    creds = json.loads(creds_json)
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w") as f:
        json.dump(creds, f)
    return path
