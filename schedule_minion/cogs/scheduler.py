"""Scheduler cog: message listener, intent router, and weekly summary."""

from __future__ import annotations

import datetime as dt
import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from discord.ext import commands, tasks

from schedule_minion.constants import ALL_FAMILY
from schedule_minion.models.events import IntentType
from schedule_minion.views.confirmations import ConfirmView

if TYPE_CHECKING:
    import discord

    from schedule_minion.config import Settings
    from schedule_minion.models.events import (
        CalendarEvent,
        FamilyMember,
        ParsedIntent,
    )
    from schedule_minion.services.calendar_service import CalendarService
    from schedule_minion.services.nlp_service import NLPService

logger = logging.getLogger(__name__)


class SchedulerCog(commands.Cog):
    """Discord cog that handles scheduling via natural language."""

    def __init__(
        self,
        bot: commands.Bot,
        settings: Settings,
        calendar_service: CalendarService,
        nlp_service: NLPService,
    ) -> None:
        self.bot = bot
        self.settings = settings
        self.calendar_service = calendar_service
        self.nlp_service = nlp_service

    async def cog_load(self) -> None:
        """Start background tasks when cog loads."""
        self.weekly_summary.start()

    async def cog_unload(self) -> None:
        """Cancel background tasks when cog unloads."""
        self.weekly_summary.cancel()

    # -- Message Listener --

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Listen for mentions in the schedule channel."""
        if message.author.bot:
            return

        if message.channel.id != self.settings.discord_channel_id:
            return

        if not self.bot.user or self.bot.user.id not in [
            m.id for m in message.mentions
        ]:
            return

        clean_content = message.content
        for mention in message.mentions:
            clean_content = clean_content.replace(f"<@{mention.id}>", "").strip()
            clean_content = clean_content.replace(f"<@!{mention.id}>", "").strip()

        if not clean_content:
            await message.reply("You rang? Tell me what to schedule!")
            return

        try:
            intent = await self.nlp_service.parse_message(clean_content)
        except Exception:
            logger.exception("NLP parsing failed")
            await message.reply("My brain glitched for a sec -- try saying that again?")
            return

        await self._route_intent(message, intent)

    async def _route_intent(
        self, message: discord.Message, intent: ParsedIntent
    ) -> None:
        """Route a parsed intent to the appropriate handler."""
        match intent.intent:
            case IntentType.CREATE:
                await self._handle_create(message, intent)
            case IntentType.QUERY:
                await self._handle_query(message, intent)
            case IntentType.RESCHEDULE:
                await self._handle_reschedule(message, intent)
            case IntentType.DELETE:
                await self._handle_delete(message, intent)
            case _:
                await message.reply(
                    "Hmm, I'm not sure what you're asking me to do. "
                    "Try something like: *'Dinner at Olive Garden Saturday at 6'* "
                    "or *'What's happening this week?'*"
                )

    # -- Intent Handlers --

    async def _handle_create(
        self, message: discord.Message, intent: ParsedIntent
    ) -> None:
        """Handle event creation with confirmation."""
        people_str = self._format_people(intent.people)
        time_str = self._format_time(intent.start_time, intent.end_time)
        location_str = f" at {intent.location}" if intent.location else ""

        verb = "is" if len(intent.people) == 1 else "are"
        confirmation_msg = (
            f"To confirm, {people_str} {verb} having "
            f"**{intent.title}**{location_str} on {time_str}?"
        )

        if intent.start_time and intent.end_time:
            conflicts = await self.calendar_service.find_conflicts(
                calendar_ids=[self.settings.family_calendar_id],
                start_time=intent.start_time,
                end_time=intent.end_time,
            )
            if conflicts:
                conflict_lines = "\n".join(
                    f"  **{c.title}** ({self._format_time(c.start_time, c.end_time)})"
                    for c in conflicts
                )
                confirmation_msg += (
                    f"\n\n**Heads up -- possible conflicts:**\n{conflict_lines}"
                )

        settings = self.settings
        cal_service = self.calendar_service

        start = intent.start_time
        end = intent.end_time

        async def on_confirm() -> str:
            if not start or not end:
                return "Hmm, I need both a start and end time to create that event."
            try:
                event = await cal_service.create_event(
                    calendar_id=settings.family_calendar_id,
                    title=intent.title or "Family Event",
                    start_time=start,
                    end_time=end,
                    attendees=intent.people,
                    location=intent.location,
                )
                return (
                    f"Done! **{event.title}** is on the books. "
                    f"Schedule Minion has served."
                )
            except Exception:
                logger.exception("Failed to create event")
                return "Something went wrong creating the event. Try again?"

        view = ConfirmView(on_confirm=on_confirm)
        await message.reply(confirmation_msg, view=view)

    async def _handle_query(
        self, message: discord.Message, intent: ParsedIntent
    ) -> None:
        """Handle event query."""
        if not intent.start_time:
            await message.reply(
                "When are you asking about? Try: *'What's happening this Friday?'*"
            )
            return

        time_min = intent.start_time
        time_max = intent.end_time or intent.start_time.replace(
            hour=23, minute=59, second=59
        )

        events = await self.calendar_service.get_events(
            calendar_ids=[self.settings.family_calendar_id],
            time_min=time_min,
            time_max=time_max,
        )

        if not events:
            date_str = intent.start_time.strftime("%A, %B %-d")
            await message.reply(
                f"Nothing scheduled for {date_str} yet! "
                f"Wide open -- the world is your oyster."
            )
            return

        event_lines = "\n".join(
            f"* **{e.title}** -- "
            f"{self._format_time(e.start_time, e.end_time)}"
            + (f" at {e.location}" if e.location else "")
            + self._format_attendees(e.attendees)
            for e in sorted(events, key=lambda ev: ev.start_time)
        )
        date_str = intent.start_time.strftime("%A, %B %-d")
        people_str = self._format_people(intent.people)
        verb = "has" if len(intent.people) == 1 else "have"
        await message.reply(
            f"Here's what {people_str} {verb} going on {date_str}:\n\n{event_lines}"
        )

    async def _handle_reschedule(
        self, message: discord.Message, intent: ParsedIntent
    ) -> None:
        """Handle event rescheduling with confirmation."""
        if not intent.search_query:
            await message.reply(
                "Which event should I reschedule? "
                "Try: *'Move Layla's dentist to next Thursday at 3'*"
            )
            return

        now = datetime.now(ZoneInfo(self.settings.timezone))
        events = await self.calendar_service.get_events(
            calendar_ids=[self.settings.family_calendar_id],
            time_min=now,
            time_max=now + timedelta(days=90),
        )

        matching = [
            e
            for e in events
            if intent.search_query and intent.search_query.lower() in e.title.lower()
        ]

        if not matching:
            await message.reply(
                f"I couldn't find anything matching "
                f"**{intent.search_query}** on the calendar."
            )
            return

        target = matching[0]
        time_str = self._format_time(intent.start_time, intent.end_time)
        attendees_str = self._format_attendees(target.attendees)
        confirmation_msg = f"Move **{target.title}**{attendees_str} to {time_str}?"

        cal_service = self.calendar_service

        async def on_confirm() -> str:
            try:
                await cal_service.update_event(
                    calendar_id=target.calendar_id,
                    event_id=target.event_id,
                    start_time=intent.start_time,
                    end_time=intent.end_time,
                )
                return f"**{target.title}** has been rescheduled. Your minion delivers."
            except Exception:
                logger.exception("Failed to reschedule")
                return "Couldn't reschedule that one. Try again?"

        view = ConfirmView(on_confirm=on_confirm)
        await message.reply(confirmation_msg, view=view)

    async def _handle_delete(
        self, message: discord.Message, intent: ParsedIntent
    ) -> None:
        """Handle event deletion with confirmation."""
        if not intent.search_query:
            await message.reply(
                "Which event should I cancel? Try: *'Cancel the dentist appointment'*"
            )
            return

        now = datetime.now(ZoneInfo(self.settings.timezone))
        events = await self.calendar_service.get_events(
            calendar_ids=[self.settings.family_calendar_id],
            time_min=now,
            time_max=now + timedelta(days=90),
        )

        matching = [
            e
            for e in events
            if intent.search_query and intent.search_query.lower() in e.title.lower()
        ]

        if not matching:
            await message.reply(
                f"Couldn't find **{intent.search_query}** on the calendar."
            )
            return

        target = matching[0]
        cal_service = self.calendar_service

        async def on_confirm() -> str:
            try:
                await cal_service.delete_event(
                    calendar_id=target.calendar_id,
                    event_id=target.event_id,
                )
                return f"**{target.title}** has been banished from the calendar."
            except Exception:
                logger.exception("Failed to delete")
                return "Couldn't delete that one. Try again?"

        attendees_str = self._format_attendees(target.attendees)
        view = ConfirmView(on_confirm=on_confirm)
        await message.reply(
            f"Cancel **{target.title}**{attendees_str} "
            f"({self._format_time(target.start_time, target.end_time)})? "
            f"This can't be undone!",
            view=view,
        )

    # -- Weekly Summary --

    @tasks.loop(time=dt.time(hour=18, minute=0, tzinfo=ZoneInfo("America/Los_Angeles")))
    async def weekly_summary(self) -> None:
        """Post a weekly summary every Sunday at 6 PM."""
        now = datetime.now(ZoneInfo(self.settings.timezone))
        if now.weekday() != 6:  # Only Sunday
            return

        channel = self.bot.get_channel(self.settings.discord_channel_id)
        if channel is None:
            return

        week_start = now + timedelta(days=1)
        week_end = week_start + timedelta(days=7)

        events = await self.calendar_service.get_events(
            calendar_ids=[self.settings.family_calendar_id],
            time_min=week_start,
            time_max=week_end,
        )

        if not events:
            await channel.send(  # type: ignore[union-attr]
                "**Weekly Briefing**\n\n"
                "Nothing on the books this week! "
                "The Minion awaits your commands."
            )
            return

        events.sort(key=lambda e: e.start_time)

        days: dict[str, list[CalendarEvent]] = {}
        for event in events:
            day_key = event.start_time.strftime("%A, %B %-d")
            days.setdefault(day_key, []).append(event)

        summary_lines: list[str] = []
        for day, day_events in days.items():
            summary_lines.append(f"\n**{day}**")
            for e in day_events:
                time_str = e.start_time.strftime("%-I:%M %p")
                loc = f" at {e.location}" if e.location else ""
                att = self._format_attendees(e.attendees)
                summary_lines.append(f"  * {time_str} -- **{e.title}**{loc}{att}")

        summary = "\n".join(summary_lines)
        await channel.send(  # type: ignore[union-attr]
            f"**Weekly Briefing -- Here's what's coming up!**\n{summary}\n\n"
            f"*Your faithful Minion is standing by for changes.*"
        )

    @weekly_summary.before_loop
    async def before_weekly_summary(self) -> None:
        """Wait for the bot to be ready before starting the loop."""
        await self.bot.wait_until_ready()

    # -- Formatting Helpers --

    @staticmethod
    def _format_attendees(attendees: list[str]) -> str:
        """Format attendee names into a parenthesized string for display."""
        if not attendees:
            return ""
        return f" ({', '.join(attendees)})"

    @staticmethod
    def _format_people(people: list[FamilyMember]) -> str:
        """Format a list of family members into a readable string."""
        if len(people) == len(ALL_FAMILY):
            return "the whole family"
        names = [p.name for p in people]
        if len(names) == 1:
            return names[0]
        return ", ".join(names[:-1]) + f" and {names[-1]}"

    @staticmethod
    def _format_time(start: datetime | None, end: datetime | None) -> str:
        """Format a time range into a readable string."""
        if not start:
            return "TBD"
        date_str = start.strftime("%A, %B %-d")
        start_str = start.strftime("%-I:%M %p")
        if end and end.date() == start.date():
            end_str = end.strftime("%-I:%M %p")
            return f"{date_str} from {start_str} to {end_str}"
        return f"{date_str} at {start_str}"
