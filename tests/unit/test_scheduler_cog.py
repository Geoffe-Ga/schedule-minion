"""Tests for schedule_minion.cogs.scheduler module."""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import discord
import pytest
from discord.ext import commands

from schedule_minion.cogs.scheduler import SchedulerCog
from schedule_minion.config import Settings
from schedule_minion.constants import ALL_FAMILY
from schedule_minion.models.events import (
    CalendarEvent,
    FamilyMember,
    IntentType,
    ParsedIntent,
)
from schedule_minion.services.calendar_service import CalendarService
from schedule_minion.services.nlp_service import NLPService

TZ = ZoneInfo("America/Los_Angeles")


@pytest.fixture
def settings() -> Settings:
    """Create test settings."""
    env = {
        "DISCORD_TOKEN": "test-token",
        "DISCORD_CHANNEL_ID": "12345",
        "ANTHROPIC_API_KEY": "sk-test",
        "GOOGLE_CREDENTIALS_PATH": "creds/sa.json",
        "FAMILY_CALENDAR_ID": "family@group.calendar.google.com",
    }
    with patch.dict(os.environ, env, clear=False):
        return Settings.from_env()


@pytest.fixture
def mock_bot() -> MagicMock:
    """Create a mock Discord bot."""
    bot = MagicMock(spec=commands.Bot)
    bot.user = MagicMock(spec=discord.User)
    bot.user.id = 99999
    bot.wait_until_ready = AsyncMock()
    return bot


@pytest.fixture
def mock_calendar_service() -> CalendarService:
    """Create a calendar service with mocked Google API."""
    svc = CalendarService.__new__(CalendarService)
    svc.timezone = "America/Los_Angeles"
    svc._credentials_path = "fake.json"
    svc._service = MagicMock()
    # Default: find_conflicts returns no conflicts, get_events returns empty
    mock_list_execute = MagicMock(return_value={"items": []})
    svc._service.events.return_value.list.return_value.execute = mock_list_execute
    return svc


@pytest.fixture
def mock_nlp_service() -> NLPService:
    """Create an NLP service with mocked Anthropic client."""
    svc = NLPService.__new__(NLPService)
    svc.timezone = "America/Los_Angeles"
    svc.client = MagicMock()
    return svc


@pytest.fixture
def cog(
    mock_bot: MagicMock,
    settings: Settings,
    mock_calendar_service: CalendarService,
    mock_nlp_service: NLPService,
) -> SchedulerCog:
    """Create a SchedulerCog for testing."""
    return SchedulerCog(
        bot=mock_bot,
        settings=settings,
        calendar_service=mock_calendar_service,
        nlp_service=mock_nlp_service,
    )


def _make_message(
    content: str,
    bot_user: MagicMock,
    channel_id: int = 12345,
    is_bot: bool = False,
) -> MagicMock:
    """Create a mock Discord message."""
    message = MagicMock(spec=discord.Message)
    message.author = MagicMock(spec=discord.User)
    message.author.bot = is_bot
    message.channel = MagicMock()
    message.channel.id = channel_id
    message.content = content
    message.mentions = [bot_user]
    message.reply = AsyncMock()
    return message


class TestFormatPeople:
    """Tests for SchedulerCog._format_people static method."""

    def test_whole_family(self) -> None:
        assert SchedulerCog._format_people(list(ALL_FAMILY)) == "the whole family"

    def test_single_person(self) -> None:
        member = FamilyMember(
            name="Layla", email="l@example.com", calendar_id="l@example.com"
        )
        assert SchedulerCog._format_people([member]) == "Layla"

    def test_two_people(self) -> None:
        members = [
            FamilyMember(name="Dad", email="d@example.com", calendar_id="d"),
            FamilyMember(name="Mom", email="m@example.com", calendar_id="m"),
        ]
        assert SchedulerCog._format_people(members) == "Dad and Mom"

    def test_three_people(self) -> None:
        members = [
            FamilyMember(name="Dad", email="d@example.com", calendar_id="d"),
            FamilyMember(name="Mom", email="m@example.com", calendar_id="m"),
            FamilyMember(name="Layla", email="l@example.com", calendar_id="l"),
        ]
        assert SchedulerCog._format_people(members) == "Dad, Mom and Layla"


class TestFormatTime:
    """Tests for SchedulerCog._format_time static method."""

    def test_no_start_time(self) -> None:
        assert SchedulerCog._format_time(None, None) == "TBD"

    def test_start_only(self) -> None:
        start = datetime(2026, 3, 7, 13, 0, tzinfo=TZ)
        result = SchedulerCog._format_time(start, None)
        assert "Saturday" in result
        assert "1:00 PM" in result

    def test_same_day_range(self) -> None:
        start = datetime(2026, 3, 7, 13, 0, tzinfo=TZ)
        end = datetime(2026, 3, 7, 14, 0, tzinfo=TZ)
        result = SchedulerCog._format_time(start, end)
        assert "from" in result
        assert "to" in result
        assert "1:00 PM" in result
        assert "2:00 PM" in result


class TestOnMessage:
    """Tests for the on_message listener."""

    @pytest.mark.asyncio
    async def test_ignores_bot_messages(self, cog: SchedulerCog) -> None:
        message = _make_message("test", cog.bot.user, is_bot=True)
        await cog.on_message(message)
        message.reply.assert_not_called()

    @pytest.mark.asyncio
    async def test_ignores_wrong_channel(self, cog: SchedulerCog) -> None:
        message = _make_message("test", cog.bot.user, channel_id=99999)
        await cog.on_message(message)
        message.reply.assert_not_called()

    @pytest.mark.asyncio
    async def test_ignores_no_mention(self, cog: SchedulerCog) -> None:
        message = _make_message("test", cog.bot.user)
        message.mentions = []
        await cog.on_message(message)
        message.reply.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_content_after_mention(self, cog: SchedulerCog) -> None:
        message = _make_message(f"<@{cog.bot.user.id}>", cog.bot.user)
        await cog.on_message(message)
        message.reply.assert_awaited_once()
        reply_text = message.reply.call_args.args[0]
        assert "Tell me what to schedule" in reply_text

    @pytest.mark.asyncio
    async def test_nlp_failure_sends_error(self, cog: SchedulerCog) -> None:
        cog.nlp_service.parse_message = AsyncMock(side_effect=RuntimeError("API down"))
        message = _make_message(f"<@{cog.bot.user.id}> dinner Friday", cog.bot.user)
        await cog.on_message(message)
        message.reply.assert_awaited_once()
        reply_text = message.reply.call_args.args[0]
        assert "glitched" in reply_text


class TestRouteIntent:
    """Tests for intent routing."""

    @pytest.mark.asyncio
    async def test_unknown_intent(self, cog: SchedulerCog) -> None:
        message = MagicMock(spec=discord.Message)
        message.reply = AsyncMock()
        intent = ParsedIntent(intent=IntentType.UNKNOWN)
        await cog._route_intent(message, intent)
        message.reply.assert_awaited_once()
        reply_text = message.reply.call_args.args[0]
        assert "not sure" in reply_text

    @pytest.mark.asyncio
    async def test_create_intent_routes(self, cog: SchedulerCog) -> None:
        now = datetime.now(TZ)
        intent = ParsedIntent(
            intent=IntentType.CREATE,
            title="Test Event",
            start_time=now + timedelta(days=1),
            end_time=now + timedelta(days=1, hours=1),
            people=list(ALL_FAMILY),
        )
        message = MagicMock(spec=discord.Message)
        message.reply = AsyncMock()

        await cog._route_intent(message, intent)
        message.reply.assert_awaited_once()


class TestHandleCreate:
    """Tests for create event handler."""

    @pytest.mark.asyncio
    async def test_sends_confirmation_with_title(self, cog: SchedulerCog) -> None:
        now = datetime.now(TZ)
        intent = ParsedIntent(
            intent=IntentType.CREATE,
            title="Pizza Night",
            start_time=now + timedelta(days=1),
            end_time=now + timedelta(days=1, hours=1),
            people=list(ALL_FAMILY),
        )
        message = MagicMock(spec=discord.Message)
        message.reply = AsyncMock()

        await cog._handle_create(message, intent)

        message.reply.assert_awaited_once()
        call_kwargs = message.reply.call_args
        assert "Pizza Night" in call_kwargs.args[0]

    @pytest.mark.asyncio
    async def test_create_with_location(self, cog: SchedulerCog) -> None:
        now = datetime.now(TZ)
        intent = ParsedIntent(
            intent=IntentType.CREATE,
            title="Dinner",
            start_time=now + timedelta(days=1),
            end_time=now + timedelta(days=1, hours=2),
            people=list(ALL_FAMILY),
            location="Olive Garden",
        )
        message = MagicMock(spec=discord.Message)
        message.reply = AsyncMock()

        await cog._handle_create(message, intent)

        reply_text = message.reply.call_args.args[0]
        assert "Olive Garden" in reply_text

    @pytest.mark.asyncio
    async def test_create_shows_conflicts(self, cog: SchedulerCog) -> None:
        now = datetime.now(TZ)
        conflict = CalendarEvent(
            event_id="c1",
            calendar_id="cal",
            title="Existing Event",
            start_time=now + timedelta(days=1),
            end_time=now + timedelta(days=1, hours=1),
        )
        cog.calendar_service.find_conflicts = AsyncMock(return_value=[conflict])

        intent = ParsedIntent(
            intent=IntentType.CREATE,
            title="New Event",
            start_time=now + timedelta(days=1),
            end_time=now + timedelta(days=1, hours=1),
            people=list(ALL_FAMILY),
        )
        message = MagicMock(spec=discord.Message)
        message.reply = AsyncMock()

        await cog._handle_create(message, intent)

        reply_text = message.reply.call_args.args[0]
        assert "conflicts" in reply_text
        assert "Existing Event" in reply_text


class TestCreateOnConfirmCallback:
    """Tests for the on_confirm closure inside _handle_create."""

    @pytest.mark.asyncio
    async def test_on_confirm_creates_event(self, cog: SchedulerCog) -> None:
        now = datetime.now(TZ)
        cog.calendar_service.create_event = AsyncMock(
            return_value=CalendarEvent(
                event_id="new-1",
                calendar_id="cal",
                title="Pizza Night",
                start_time=now + timedelta(days=1),
                end_time=now + timedelta(days=1, hours=1),
            )
        )
        intent = ParsedIntent(
            intent=IntentType.CREATE,
            title="Pizza Night",
            start_time=now + timedelta(days=1),
            end_time=now + timedelta(days=1, hours=1),
            people=list(ALL_FAMILY),
        )
        message = MagicMock(spec=discord.Message)
        message.reply = AsyncMock()

        await cog._handle_create(message, intent)

        # Extract the ConfirmView and call on_confirm
        call_kwargs = message.reply.call_args
        view = call_kwargs.kwargs["view"]
        result = await view.on_confirm()
        assert "on the books" in result
        cog.calendar_service.create_event.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_on_confirm_handles_error(self, cog: SchedulerCog) -> None:
        now = datetime.now(TZ)
        cog.calendar_service.create_event = AsyncMock(
            side_effect=RuntimeError("API error")
        )
        intent = ParsedIntent(
            intent=IntentType.CREATE,
            title="Event",
            start_time=now + timedelta(days=1),
            end_time=now + timedelta(days=1, hours=1),
            people=list(ALL_FAMILY),
        )
        message = MagicMock(spec=discord.Message)
        message.reply = AsyncMock()

        await cog._handle_create(message, intent)

        view = message.reply.call_args.kwargs["view"]
        result = await view.on_confirm()
        assert "went wrong" in result


class TestHandleQuery:
    """Tests for query event handler."""

    @pytest.mark.asyncio
    async def test_query_no_start_time_asks_when(self, cog: SchedulerCog) -> None:
        intent = ParsedIntent(intent=IntentType.QUERY, people=list(ALL_FAMILY))
        message = MagicMock(spec=discord.Message)
        message.reply = AsyncMock()

        await cog._handle_query(message, intent)

        reply_text = message.reply.call_args.args[0]
        assert "When" in reply_text

    @pytest.mark.asyncio
    async def test_query_no_events_found(self, cog: SchedulerCog) -> None:
        now = datetime.now(TZ)
        intent = ParsedIntent(
            intent=IntentType.QUERY,
            start_time=now + timedelta(days=1),
            people=list(ALL_FAMILY),
        )
        cog.calendar_service.get_events = AsyncMock(return_value=[])

        message = MagicMock(spec=discord.Message)
        message.reply = AsyncMock()

        await cog._handle_query(message, intent)

        reply_text = message.reply.call_args.args[0]
        assert "Nothing scheduled" in reply_text

    @pytest.mark.asyncio
    async def test_query_returns_events(self, cog: SchedulerCog) -> None:
        now = datetime.now(TZ)
        event = CalendarEvent(
            event_id="e1",
            calendar_id="cal",
            title="Soccer Practice",
            start_time=now + timedelta(days=1, hours=2),
            end_time=now + timedelta(days=1, hours=3),
        )
        cog.calendar_service.get_events = AsyncMock(return_value=[event])

        intent = ParsedIntent(
            intent=IntentType.QUERY,
            start_time=now + timedelta(days=1),
            people=list(ALL_FAMILY),
        )
        message = MagicMock(spec=discord.Message)
        message.reply = AsyncMock()

        await cog._handle_query(message, intent)

        reply_text = message.reply.call_args.args[0]
        assert "Soccer Practice" in reply_text


class TestHandleReschedule:
    """Tests for reschedule handler."""

    @pytest.mark.asyncio
    async def test_no_search_query_asks(self, cog: SchedulerCog) -> None:
        intent = ParsedIntent(intent=IntentType.RESCHEDULE)
        message = MagicMock(spec=discord.Message)
        message.reply = AsyncMock()

        await cog._handle_reschedule(message, intent)

        reply_text = message.reply.call_args.args[0]
        assert "Which event" in reply_text

    @pytest.mark.asyncio
    async def test_no_matching_event(self, cog: SchedulerCog) -> None:
        now = datetime.now(TZ)
        cog.calendar_service.get_events = AsyncMock(return_value=[])

        intent = ParsedIntent(
            intent=IntentType.RESCHEDULE,
            search_query="dentist",
            start_time=now + timedelta(days=3),
            end_time=now + timedelta(days=3, hours=1),
        )
        message = MagicMock(spec=discord.Message)
        message.reply = AsyncMock()

        await cog._handle_reschedule(message, intent)

        reply_text = message.reply.call_args.args[0]
        assert "couldn't find" in reply_text

    @pytest.mark.asyncio
    async def test_matching_event_sends_confirmation(self, cog: SchedulerCog) -> None:
        now = datetime.now(TZ)
        event = CalendarEvent(
            event_id="e1",
            calendar_id="cal",
            title="Dentist Appointment",
            start_time=now + timedelta(days=2),
            end_time=now + timedelta(days=2, hours=1),
        )
        cog.calendar_service.get_events = AsyncMock(return_value=[event])

        intent = ParsedIntent(
            intent=IntentType.RESCHEDULE,
            search_query="dentist",
            start_time=now + timedelta(days=5),
            end_time=now + timedelta(days=5, hours=1),
        )
        message = MagicMock(spec=discord.Message)
        message.reply = AsyncMock()

        await cog._handle_reschedule(message, intent)

        reply_text = message.reply.call_args.args[0]
        assert "Move" in reply_text
        assert "Dentist" in reply_text


class TestRescheduleOnConfirmCallback:
    """Tests for on_confirm closure inside _handle_reschedule."""

    @pytest.mark.asyncio
    async def test_on_confirm_updates_event(self, cog: SchedulerCog) -> None:
        now = datetime.now(TZ)
        event = CalendarEvent(
            event_id="e1",
            calendar_id="cal",
            title="Dentist",
            start_time=now + timedelta(days=2),
            end_time=now + timedelta(days=2, hours=1),
        )
        cog.calendar_service.get_events = AsyncMock(return_value=[event])
        cog.calendar_service.update_event = AsyncMock(return_value=event)

        intent = ParsedIntent(
            intent=IntentType.RESCHEDULE,
            search_query="dentist",
            start_time=now + timedelta(days=5),
            end_time=now + timedelta(days=5, hours=1),
        )
        message = MagicMock(spec=discord.Message)
        message.reply = AsyncMock()

        await cog._handle_reschedule(message, intent)

        view = message.reply.call_args.kwargs["view"]
        result = await view.on_confirm()
        assert "rescheduled" in result

    @pytest.mark.asyncio
    async def test_on_confirm_handles_error(self, cog: SchedulerCog) -> None:
        now = datetime.now(TZ)
        event = CalendarEvent(
            event_id="e1",
            calendar_id="cal",
            title="Dentist",
            start_time=now + timedelta(days=2),
            end_time=now + timedelta(days=2, hours=1),
        )
        cog.calendar_service.get_events = AsyncMock(return_value=[event])
        cog.calendar_service.update_event = AsyncMock(side_effect=RuntimeError("fail"))

        intent = ParsedIntent(
            intent=IntentType.RESCHEDULE,
            search_query="dentist",
            start_time=now + timedelta(days=5),
            end_time=now + timedelta(days=5, hours=1),
        )
        message = MagicMock(spec=discord.Message)
        message.reply = AsyncMock()

        await cog._handle_reschedule(message, intent)

        view = message.reply.call_args.kwargs["view"]
        result = await view.on_confirm()
        assert "Couldn't reschedule" in result


class TestHandleDelete:
    """Tests for delete handler."""

    @pytest.mark.asyncio
    async def test_no_search_query_asks(self, cog: SchedulerCog) -> None:
        intent = ParsedIntent(intent=IntentType.DELETE)
        message = MagicMock(spec=discord.Message)
        message.reply = AsyncMock()

        await cog._handle_delete(message, intent)

        reply_text = message.reply.call_args.args[0]
        assert "Which event" in reply_text

    @pytest.mark.asyncio
    async def test_no_matching_event(self, cog: SchedulerCog) -> None:
        cog.calendar_service.get_events = AsyncMock(return_value=[])

        intent = ParsedIntent(
            intent=IntentType.DELETE,
            search_query="dentist",
        )
        message = MagicMock(spec=discord.Message)
        message.reply = AsyncMock()

        await cog._handle_delete(message, intent)

        reply_text = message.reply.call_args.args[0]
        assert "Couldn't find" in reply_text

    @pytest.mark.asyncio
    async def test_matching_event_sends_confirmation(self, cog: SchedulerCog) -> None:
        now = datetime.now(TZ)
        event = CalendarEvent(
            event_id="e1",
            calendar_id="cal",
            title="Soccer Practice",
            start_time=now + timedelta(days=2),
            end_time=now + timedelta(days=2, hours=1),
        )
        cog.calendar_service.get_events = AsyncMock(return_value=[event])

        intent = ParsedIntent(
            intent=IntentType.DELETE,
            search_query="soccer",
        )
        message = MagicMock(spec=discord.Message)
        message.reply = AsyncMock()

        await cog._handle_delete(message, intent)

        reply_text = message.reply.call_args.args[0]
        assert "Cancel" in reply_text
        assert "Soccer Practice" in reply_text
        assert "can't be undone" in reply_text


class TestDeleteOnConfirmCallback:
    """Tests for on_confirm closure inside _handle_delete."""

    @pytest.mark.asyncio
    async def test_on_confirm_deletes_event(self, cog: SchedulerCog) -> None:
        now = datetime.now(TZ)
        event = CalendarEvent(
            event_id="e1",
            calendar_id="cal",
            title="Soccer Practice",
            start_time=now + timedelta(days=2),
            end_time=now + timedelta(days=2, hours=1),
        )
        cog.calendar_service.get_events = AsyncMock(return_value=[event])
        cog.calendar_service.delete_event = AsyncMock(return_value=True)

        intent = ParsedIntent(
            intent=IntentType.DELETE,
            search_query="soccer",
        )
        message = MagicMock(spec=discord.Message)
        message.reply = AsyncMock()

        await cog._handle_delete(message, intent)

        view = message.reply.call_args.kwargs["view"]
        result = await view.on_confirm()
        assert "banished" in result

    @pytest.mark.asyncio
    async def test_on_confirm_handles_error(self, cog: SchedulerCog) -> None:
        now = datetime.now(TZ)
        event = CalendarEvent(
            event_id="e1",
            calendar_id="cal",
            title="Soccer",
            start_time=now + timedelta(days=2),
            end_time=now + timedelta(days=2, hours=1),
        )
        cog.calendar_service.get_events = AsyncMock(return_value=[event])
        cog.calendar_service.delete_event = AsyncMock(side_effect=RuntimeError("fail"))

        intent = ParsedIntent(
            intent=IntentType.DELETE,
            search_query="soccer",
        )
        message = MagicMock(spec=discord.Message)
        message.reply = AsyncMock()

        await cog._handle_delete(message, intent)

        view = message.reply.call_args.kwargs["view"]
        result = await view.on_confirm()
        assert "Couldn't delete" in result


class TestCogLifecycle:
    """Tests for cog_load and cog_unload."""

    @pytest.mark.asyncio
    async def test_cog_load_starts_weekly_summary(self, cog: SchedulerCog) -> None:
        with patch.object(cog.weekly_summary, "start") as mock_start:
            await cog.cog_load()
            mock_start.assert_called_once()

    @pytest.mark.asyncio
    async def test_cog_unload_cancels_weekly_summary(self, cog: SchedulerCog) -> None:
        with patch.object(cog.weekly_summary, "cancel") as mock_cancel:
            await cog.cog_unload()
            mock_cancel.assert_called_once()


class TestRouteIntentBranches:
    """Tests for all _route_intent branches."""

    @pytest.mark.asyncio
    async def test_routes_query(self, cog: SchedulerCog) -> None:
        intent = ParsedIntent(intent=IntentType.QUERY, people=list(ALL_FAMILY))
        message = MagicMock(spec=discord.Message)
        message.reply = AsyncMock()
        with patch.object(cog, "_handle_query", new_callable=AsyncMock) as mock:
            await cog._route_intent(message, intent)
            mock.assert_awaited_once_with(message, intent)

    @pytest.mark.asyncio
    async def test_routes_reschedule(self, cog: SchedulerCog) -> None:
        intent = ParsedIntent(intent=IntentType.RESCHEDULE)
        message = MagicMock(spec=discord.Message)
        message.reply = AsyncMock()
        with patch.object(cog, "_handle_reschedule", new_callable=AsyncMock) as mock:
            await cog._route_intent(message, intent)
            mock.assert_awaited_once_with(message, intent)

    @pytest.mark.asyncio
    async def test_routes_delete(self, cog: SchedulerCog) -> None:
        intent = ParsedIntent(intent=IntentType.DELETE)
        message = MagicMock(spec=discord.Message)
        message.reply = AsyncMock()
        with patch.object(cog, "_handle_delete", new_callable=AsyncMock) as mock:
            await cog._route_intent(message, intent)
            mock.assert_awaited_once_with(message, intent)


class TestOnMessageParseAndRoute:
    """Tests for on_message successfully parsing and routing."""

    @pytest.mark.asyncio
    async def test_successful_parse_routes_intent(self, cog: SchedulerCog) -> None:
        now = datetime.now(TZ)
        parsed = ParsedIntent(
            intent=IntentType.CREATE,
            title="Test",
            start_time=now + timedelta(days=1),
            end_time=now + timedelta(days=1, hours=1),
            people=list(ALL_FAMILY),
        )
        cog.nlp_service.parse_message = AsyncMock(return_value=parsed)

        message = _make_message(f"<@{cog.bot.user.id}> dinner Friday", cog.bot.user)

        with patch.object(cog, "_route_intent", new_callable=AsyncMock) as mock_route:
            await cog.on_message(message)
            mock_route.assert_awaited_once()


class TestBeforeWeeklySummary:
    """Tests for before_weekly_summary."""

    @pytest.mark.asyncio
    async def test_waits_until_ready(self, cog: SchedulerCog) -> None:
        await cog.before_weekly_summary()
        cog.bot.wait_until_ready.assert_awaited_once()


class TestWeeklySummary:
    """Tests for the weekly summary task."""

    @pytest.mark.asyncio
    async def test_skips_non_sunday(self, cog: SchedulerCog) -> None:
        # Monday = weekday 0
        monday = datetime(2026, 3, 2, 18, 0, tzinfo=TZ)
        with patch("schedule_minion.cogs.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = monday
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            await cog.weekly_summary.coro(cog)
        # No channel.send should be called
        cog.bot.get_channel.assert_not_called()

    @pytest.mark.asyncio
    async def test_sunday_no_events(self, cog: SchedulerCog) -> None:
        sunday = datetime(2026, 3, 1, 18, 0, tzinfo=TZ)  # Sunday
        mock_channel = MagicMock()
        mock_channel.send = AsyncMock()
        cog.bot.get_channel.return_value = mock_channel
        cog.calendar_service.get_events = AsyncMock(return_value=[])

        with patch("schedule_minion.cogs.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = sunday
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            await cog.weekly_summary.coro(cog)

        mock_channel.send.assert_awaited_once()
        send_text = mock_channel.send.call_args.args[0]
        assert "Nothing on the books" in send_text

    @pytest.mark.asyncio
    async def test_sunday_with_events(self, cog: SchedulerCog) -> None:
        sunday = datetime(2026, 3, 1, 18, 0, tzinfo=TZ)
        event = CalendarEvent(
            event_id="e1",
            calendar_id="cal",
            title="Soccer Practice",
            start_time=datetime(2026, 3, 3, 16, 0, tzinfo=TZ),
            end_time=datetime(2026, 3, 3, 17, 0, tzinfo=TZ),
        )
        mock_channel = MagicMock()
        mock_channel.send = AsyncMock()
        cog.bot.get_channel.return_value = mock_channel
        cog.calendar_service.get_events = AsyncMock(return_value=[event])

        with patch("schedule_minion.cogs.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = sunday
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            await cog.weekly_summary.coro(cog)

        mock_channel.send.assert_awaited_once()
        send_text = mock_channel.send.call_args.args[0]
        assert "Soccer Practice" in send_text

    @pytest.mark.asyncio
    async def test_sunday_no_channel(self, cog: SchedulerCog) -> None:
        sunday = datetime(2026, 3, 1, 18, 0, tzinfo=TZ)
        cog.bot.get_channel.return_value = None

        with patch("schedule_minion.cogs.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = sunday
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            await cog.weekly_summary.coro(cog)

    @pytest.mark.asyncio
    async def test_sunday_events_show_attendees(self, cog: SchedulerCog) -> None:
        sunday = datetime(2026, 3, 1, 18, 0, tzinfo=TZ)
        event = CalendarEvent(
            event_id="e1",
            calendar_id="cal",
            title="Soccer Practice",
            start_time=datetime(2026, 3, 3, 16, 0, tzinfo=TZ),
            end_time=datetime(2026, 3, 3, 17, 0, tzinfo=TZ),
            attendees=["Dad", "Layla"],
        )
        mock_channel = MagicMock()
        mock_channel.send = AsyncMock()
        cog.bot.get_channel.return_value = mock_channel
        cog.calendar_service.get_events = AsyncMock(return_value=[event])

        with patch("schedule_minion.cogs.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = sunday
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            await cog.weekly_summary.coro(cog)

        send_text = mock_channel.send.call_args.args[0]
        assert "(Dad, Layla)" in send_text


class TestFormatAttendees:
    """Tests for SchedulerCog._format_attendees static method."""

    def test_empty_attendees(self) -> None:
        assert SchedulerCog._format_attendees([]) == ""

    def test_single_attendee(self) -> None:
        assert SchedulerCog._format_attendees(["Dad"]) == " (Dad)"

    def test_multiple_attendees(self) -> None:
        result = SchedulerCog._format_attendees(["Dad", "Layla"])
        assert result == " (Dad, Layla)"


class TestQueryDisplayAttendees:
    """Tests for attendees in query results."""

    @pytest.mark.asyncio
    async def test_query_shows_attendees(self, cog: SchedulerCog) -> None:
        now = datetime.now(TZ)
        event = CalendarEvent(
            event_id="e1",
            calendar_id="cal",
            title="Soccer Practice",
            start_time=now + timedelta(days=1, hours=2),
            end_time=now + timedelta(days=1, hours=3),
            attendees=["Dad", "Layla"],
        )
        cog.calendar_service.get_events = AsyncMock(return_value=[event])

        intent = ParsedIntent(
            intent=IntentType.QUERY,
            start_time=now + timedelta(days=1),
            people=list(ALL_FAMILY),
        )
        message = MagicMock(spec=discord.Message)
        message.reply = AsyncMock()

        await cog._handle_query(message, intent)

        reply_text = message.reply.call_args.args[0]
        assert "(Dad, Layla)" in reply_text

    @pytest.mark.asyncio
    async def test_query_no_attendees_no_parens(self, cog: SchedulerCog) -> None:
        now = datetime.now(TZ)
        event = CalendarEvent(
            event_id="e1",
            calendar_id="cal",
            title="Solo Event",
            start_time=now + timedelta(days=1, hours=2),
            end_time=now + timedelta(days=1, hours=3),
        )
        cog.calendar_service.get_events = AsyncMock(return_value=[event])

        intent = ParsedIntent(
            intent=IntentType.QUERY,
            start_time=now + timedelta(days=1),
            people=list(ALL_FAMILY),
        )
        message = MagicMock(spec=discord.Message)
        message.reply = AsyncMock()

        await cog._handle_query(message, intent)

        reply_text = message.reply.call_args.args[0]
        assert "Solo Event" in reply_text
        assert "(" not in reply_text


class TestDeleteDisplayAttendees:
    """Tests for attendees in delete confirmation."""

    @pytest.mark.asyncio
    async def test_delete_shows_attendees(self, cog: SchedulerCog) -> None:
        now = datetime.now(TZ)
        event = CalendarEvent(
            event_id="e1",
            calendar_id="cal",
            title="Soccer Practice",
            start_time=now + timedelta(days=2),
            end_time=now + timedelta(days=2, hours=1),
            attendees=["Dad", "Layla"],
        )
        cog.calendar_service.get_events = AsyncMock(return_value=[event])

        intent = ParsedIntent(
            intent=IntentType.DELETE,
            search_query="soccer",
        )
        message = MagicMock(spec=discord.Message)
        message.reply = AsyncMock()

        await cog._handle_delete(message, intent)

        reply_text = message.reply.call_args.args[0]
        assert "(Dad, Layla)" in reply_text


class TestRescheduleDisplayAttendees:
    """Tests for attendees in reschedule confirmation."""

    @pytest.mark.asyncio
    async def test_reschedule_shows_attendees(self, cog: SchedulerCog) -> None:
        now = datetime.now(TZ)
        event = CalendarEvent(
            event_id="e1",
            calendar_id="cal",
            title="Dentist Appointment",
            start_time=now + timedelta(days=2),
            end_time=now + timedelta(days=2, hours=1),
            attendees=["Mom", "Niall"],
        )
        cog.calendar_service.get_events = AsyncMock(return_value=[event])

        intent = ParsedIntent(
            intent=IntentType.RESCHEDULE,
            search_query="dentist",
            start_time=now + timedelta(days=5),
            end_time=now + timedelta(days=5, hours=1),
        )
        message = MagicMock(spec=discord.Message)
        message.reply = AsyncMock()

        await cog._handle_reschedule(message, intent)

        reply_text = message.reply.call_args.args[0]
        assert "(Mom, Niall)" in reply_text
