"""Tests for schedule_minion.constants module."""

from __future__ import annotations

from schedule_minion.constants import (
    ALL_FAMILY,
    FAMILY_MEMBERS,
    NAME_ALIASES,
)
from schedule_minion.models.events import FamilyMember


class TestFamilyMembers:
    """Tests for family member constants."""

    def test_four_family_members(self) -> None:
        assert len(FAMILY_MEMBERS) == 4

    def test_dad_exists(self) -> None:
        assert "dad" in FAMILY_MEMBERS
        assert FAMILY_MEMBERS["dad"].name == "Dad"

    def test_mom_exists(self) -> None:
        assert "mom" in FAMILY_MEMBERS
        assert FAMILY_MEMBERS["mom"].name == "Mom"

    def test_layla_exists(self) -> None:
        assert "layla" in FAMILY_MEMBERS
        assert FAMILY_MEMBERS["layla"].name == "Layla"

    def test_niall_exists(self) -> None:
        assert "niall" in FAMILY_MEMBERS
        assert FAMILY_MEMBERS["niall"].name == "Niall"

    def test_all_members_are_family_member_instances(self) -> None:
        for member in FAMILY_MEMBERS.values():
            assert isinstance(member, FamilyMember)

    def test_all_members_have_email(self) -> None:
        for member in FAMILY_MEMBERS.values():
            assert "@" in member.email


class TestNameAliases:
    """Tests for name alias mapping."""

    def test_geoff_maps_to_dad(self) -> None:
        assert NAME_ALIASES["geoff"] == "dad"

    def test_free_maps_to_mom(self) -> None:
        assert NAME_ALIASES["free"] == "mom"

    def test_all_aliases_resolve_to_valid_members(self) -> None:
        for alias, key in NAME_ALIASES.items():
            assert key in FAMILY_MEMBERS, (
                f"Alias '{alias}' -> '{key}' not in FAMILY_MEMBERS"
            )


class TestAllFamily:
    """Tests for ALL_FAMILY list."""

    def test_all_family_has_four_members(self) -> None:
        assert len(ALL_FAMILY) == 4

    def test_all_family_matches_family_members_values(self) -> None:
        members = list(FAMILY_MEMBERS.values())
        assert sorted(ALL_FAMILY, key=lambda m: m.name) == sorted(
            members, key=lambda m: m.name
        )
