"""Tests for schedule_minion.services.nlp_service module."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from anthropic.types import TextBlock

from schedule_minion.models.events import IntentType
from schedule_minion.services.nlp_service import NLPService


def _mock_claude_response(data: dict) -> MagicMock:
    """Create a mock Claude API response."""
    response = MagicMock()
    text_block = MagicMock(spec=TextBlock)
    text_block.text = json.dumps(data)
    response.content = [text_block]
    return response


class TestNLPServiceParsing:
    """Tests for NLP service message parsing."""

    @pytest.mark.asyncio
    async def test_parse_create_intent(self) -> None:
        mock_response = _mock_claude_response(
            {
                "intent": "create",
                "title": "Jimmy Hang Outs",
                "start_time": "2026-03-07T13:00:00-08:00",
                "end_time": "2026-03-07T14:00:00-08:00",
                "location": None,
                "people": [],
                "search_query": None,
                "notes": None,
            }
        )

        service = NLPService(api_key="fake", timezone="America/Los_Angeles")
        service.client = MagicMock()
        service.client.messages = MagicMock()
        service.client.messages.create = AsyncMock(return_value=mock_response)

        intent = await service.parse_message(
            "We're hanging out with Jimmy at 1 pm a week from Saturday"
        )

        assert intent.intent == IntentType.CREATE
        assert "Jimmy" in (intent.title or "")
        assert len(intent.people) == 4  # whole family (empty people list)

    @pytest.mark.asyncio
    async def test_parse_query_intent(self) -> None:
        mock_response = _mock_claude_response(
            {
                "intent": "query",
                "title": None,
                "start_time": "2026-03-04T00:00:00-08:00",
                "end_time": "2026-03-04T23:59:59-08:00",
                "location": None,
                "people": ["layla"],
                "search_query": None,
                "notes": None,
            }
        )

        service = NLPService(api_key="fake", timezone="America/Los_Angeles")
        service.client = MagicMock()
        service.client.messages = MagicMock()
        service.client.messages.create = AsyncMock(return_value=mock_response)

        intent = await service.parse_message("Is Layla free on Wednesday?")

        assert intent.intent == IntentType.QUERY
        assert len(intent.people) == 1
        assert intent.people[0].name == "Layla"

    @pytest.mark.asyncio
    async def test_parse_delete_intent(self) -> None:
        mock_response = _mock_claude_response(
            {
                "intent": "delete",
                "title": None,
                "start_time": None,
                "end_time": None,
                "location": None,
                "people": [],
                "search_query": "dentist",
                "notes": None,
            }
        )

        service = NLPService(api_key="fake", timezone="America/Los_Angeles")
        service.client = MagicMock()
        service.client.messages = MagicMock()
        service.client.messages.create = AsyncMock(return_value=mock_response)

        intent = await service.parse_message("Cancel the dentist appointment")

        assert intent.intent == IntentType.DELETE
        assert intent.search_query == "dentist"

    @pytest.mark.asyncio
    async def test_parse_reschedule_intent(self) -> None:
        mock_response = _mock_claude_response(
            {
                "intent": "reschedule",
                "title": None,
                "start_time": "2026-03-05T16:00:00-08:00",
                "end_time": "2026-03-05T17:00:00-08:00",
                "location": None,
                "people": [],
                "search_query": "soccer",
                "notes": None,
            }
        )

        service = NLPService(api_key="fake", timezone="America/Los_Angeles")
        service.client = MagicMock()
        service.client.messages = MagicMock()
        service.client.messages.create = AsyncMock(return_value=mock_response)

        intent = await service.parse_message("Move soccer practice to Thursday at 4")

        assert intent.intent == IntentType.RESCHEDULE
        assert intent.search_query == "soccer"
        assert intent.start_time is not None

    @pytest.mark.asyncio
    async def test_strips_markdown_code_fences(self) -> None:
        data = {
            "intent": "create",
            "title": "Test",
            "start_time": "2026-03-07T13:00:00-08:00",
            "end_time": "2026-03-07T14:00:00-08:00",
            "location": None,
            "people": [],
            "search_query": None,
            "notes": None,
        }
        response = MagicMock()
        text_block = MagicMock(spec=TextBlock)
        text_block.text = f"```json\n{json.dumps(data)}\n```"
        response.content = [text_block]

        service = NLPService(api_key="fake", timezone="America/Los_Angeles")
        service.client = MagicMock()
        service.client.messages = MagicMock()
        service.client.messages.create = AsyncMock(return_value=response)

        intent = await service.parse_message("Dinner at 6")

        assert intent.intent == IntentType.CREATE

    @pytest.mark.asyncio
    async def test_preserves_raw_message(self) -> None:
        mock_response = _mock_claude_response(
            {
                "intent": "unknown",
                "title": None,
                "start_time": None,
                "end_time": None,
                "location": None,
                "people": [],
                "search_query": None,
                "notes": None,
            }
        )

        service = NLPService(api_key="fake", timezone="America/Los_Angeles")
        service.client = MagicMock()
        service.client.messages = MagicMock()
        service.client.messages.create = AsyncMock(return_value=mock_response)

        msg = "What time is it?"
        intent = await service.parse_message(msg)

        assert intent.raw_message == msg

    @pytest.mark.asyncio
    async def test_parse_with_location(self) -> None:
        mock_response = _mock_claude_response(
            {
                "intent": "create",
                "title": "Pizza Night",
                "start_time": "2026-03-07T18:00:00-08:00",
                "end_time": "2026-03-07T19:00:00-08:00",
                "location": "Olive Garden",
                "people": ["dad", "mom"],
                "search_query": None,
                "notes": None,
            }
        )

        service = NLPService(api_key="fake", timezone="America/Los_Angeles")
        service.client = MagicMock()
        service.client.messages = MagicMock()
        service.client.messages.create = AsyncMock(return_value=mock_response)

        intent = await service.parse_message("Dinner at Olive Garden with Mom and Dad")

        assert intent.location == "Olive Garden"
        assert len(intent.people) == 2


class TestResolvePeople:
    """Tests for the _resolve_people static method."""

    def test_empty_list_returns_all_family(self) -> None:
        result = NLPService._resolve_people([])
        assert len(result) == 4

    def test_resolves_direct_names(self) -> None:
        result = NLPService._resolve_people(["dad", "layla"])
        assert len(result) == 2
        names = {p.name for p in result}
        assert names == {"Dad", "Layla"}

    def test_resolves_aliases(self) -> None:
        result = NLPService._resolve_people(["geoff", "free"])
        assert len(result) == 2
        names = {p.name for p in result}
        assert names == {"Dad", "Mom"}

    def test_unknown_names_return_all_family(self) -> None:
        result = NLPService._resolve_people(["jimmy", "bob"])
        assert len(result) == 4  # Falls back to all family

    def test_case_insensitive(self) -> None:
        result = NLPService._resolve_people(["DAD", "Mom"])
        assert len(result) == 2
