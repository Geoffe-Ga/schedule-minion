"""Configuration loaded from environment variables."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

from schedule_minion.auth_middleware import SECRET_ENV_VAR

API_PORT_ENV_VAR = "SCHEDULE_MINION_API_PORT"
DEFAULT_API_HOST = "127.0.0.1"
DEFAULT_API_PORT = 8003


@dataclass(frozen=True)
class ApiSettings:
    """Settings for the standalone RubotPaul API process.

    The API is the entire service (a ``systemd --user`` unit on the VPS
    bound to localhost), so no Discord credentials are required.

    Attributes:
        anthropic_api_key: Anthropic Claude API key for NLP parsing.
        family_calendar_id: Google Calendar ID for the shared family calendar.
        google_credentials_path: Path to a service-account JSON file.
        google_credentials_info: Service-account info parsed from
            ``GOOGLE_CREDENTIALS_JSON`` when no file path is set.
        timezone: IANA timezone used for calendar and NLP operations.
        host: Interface the API binds to (localhost-only on the VPS).
        port: TCP port the API listens on.
    """

    anthropic_api_key: str
    family_calendar_id: str
    google_credentials_path: str = ""
    google_credentials_info: dict[str, Any] | None = field(default=None, repr=False)
    timezone: str = "America/Los_Angeles"
    host: str = DEFAULT_API_HOST
    port: int = DEFAULT_API_PORT

    def __post_init__(self) -> None:
        """Validate field ranges after initialization.

        Raises:
            ValueError: If port is outside the valid TCP range.
        """
        if not 1 <= self.port <= 65535:
            msg = f"port must be 1-65535, got {self.port}"
            raise ValueError(msg)

    @classmethod
    def from_env(cls) -> ApiSettings:
        """Create ApiSettings from environment variables.

        ``RUBOTPAUL_SHARED_SECRET`` is validated here (fail fast at boot
        with a clear message) even though the auth middleware reads it
        from the environment on each request. Supports
        ``GOOGLE_CREDENTIALS_JSON`` as an alternative to
        ``GOOGLE_CREDENTIALS_PATH`` for platforms where credentials are
        passed as environment variables, not files.

        Returns:
            An ApiSettings instance populated from the environment.

        Raises:
            RuntimeError: If any required environment variable is unset,
                naming every missing variable.
            ValueError: If SCHEDULE_MINION_API_PORT is not a valid port.
        """
        required = ("ANTHROPIC_API_KEY", "FAMILY_CALENDAR_ID", SECRET_ENV_VAR)
        missing = [name for name in required if not os.environ.get(name)]

        google_creds_path = os.environ.get("GOOGLE_CREDENTIALS_PATH", "")
        google_creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON", "")
        if not google_creds_path and not google_creds_json:
            missing.append("GOOGLE_CREDENTIALS_PATH or GOOGLE_CREDENTIALS_JSON")
        if missing:
            msg = "missing required environment variables: " + ", ".join(missing)
            raise RuntimeError(msg)

        google_creds_info: dict[str, Any] | None = None
        if not google_creds_path:
            google_creds_info = json.loads(google_creds_json)

        raw_port = os.environ.get(API_PORT_ENV_VAR, str(DEFAULT_API_PORT))
        try:
            port = int(raw_port)
        except ValueError as exc:
            msg = f"{API_PORT_ENV_VAR} must be an integer, got {raw_port!r}"
            raise ValueError(msg) from exc

        return cls(
            anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
            family_calendar_id=os.environ["FAMILY_CALENDAR_ID"],
            google_credentials_path=google_creds_path,
            google_credentials_info=google_creds_info,
            port=port,
        )
