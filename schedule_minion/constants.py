"""Family member mapping and calendar configuration."""

from __future__ import annotations

from schedule_minion.models.events import FamilyMember

FAMILY_MEMBERS: dict[str, FamilyMember] = {
    "dad": FamilyMember(
        name="Dad",
        email="Geoffe.gallinger@gmail.com",
        calendar_id="Geoffe.gallinger@gmail.com",
    ),
    "mom": FamilyMember(
        name="Mom",
        email="Freelalala@gmail.com",
        calendar_id="Freelalala@gmail.com",
    ),
    "layla": FamilyMember(
        name="Layla",
        email="One.Bad.Baldie@gmail.com",
        calendar_id="One.Bad.Baldie@gmail.com",
    ),
    "niall": FamilyMember(
        name="Niall",
        email="ANiallation@gmail.com",
        calendar_id="ANiallation@gmail.com",
    ),
}

NAME_ALIASES: dict[str, str] = {
    "geoff": "dad",
    "daddy": "dad",
    "father": "dad",
    "free": "mom",
    "mama": "mom",
    "mommy": "mom",
    "mother": "mom",
}

ALL_FAMILY: list[FamilyMember] = list(FAMILY_MEMBERS.values())
