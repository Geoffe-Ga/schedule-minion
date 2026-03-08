# Schedule Minion — Claude Code Build Plan

> A Discord bot that eliminates invisible labor by managing the family calendar through natural language. Built with Python, Google Calendar API, Discord.py, and Claude API.

---

## Role

You are a senior Python engineer building a Discord bot called "Schedule Minion." You specialize in async Python, Google Calendar API integration, Discord.py, and natural language processing via Claude API. You follow **tracer code methodology**: wire the full skeleton end-to-end with stubs first, then replace each stub with real logic incrementally — always maintaining a working, demoable application at every phase.

## Goal

Build a Discord bot ("Schedule Minion") that lives in a dedicated `#schedule` channel and manages a family's Google Calendars through natural language. Users `@Schedule Minion` with plain English, and the bot:

1. **Creates events** — Parses natural language into calendar events with confirmation buttons
2. **Queries events** — Answers "what's happening" questions for specific people or the whole family
3. **Reschedules events** — Moves existing events with confirmation
4. **Deletes events** — Cancels events with confirmation
5. **Weekly summary** — Posts a recap of the upcoming week every Sunday evening
6. **Conflict detection** — Warns when a new event overlaps with existing ones

**Success criteria**: The bot runs in `#schedule`, parses natural language via Claude, manages real Google Calendar events, uses interactive buttons for confirmations, and handles all six features above.

## Context

### Family Setup

| Name | Role | Gmail | Calendar Strategy |
|------|------|-------|-------------------|
| Geoff | Dad | Geoffe.gallinger@gmail.com | Individual + shared |
| Free | Mom | Freelalala@gmail.com | Individual + shared |
| Layla | Kid | One.Bad.Baldie@gmail.com | Individual + shared |
| Niall | Kid | ANiallation@gmail.com | Individual + shared |

- **Shared calendar**: One family calendar all accounts can see (for family-wide events)
- **Individual calendars**: Each person's primary calendar (for personal events)
- **Default behavior**: When no names are mentioned, events go on the **shared family calendar** and are assumed to involve everyone

### Bot Personality

Schedule Minion is a **dutiful-but-cheeky servant**. Think loyal minion who's proud of their job but can't resist a little personality. Brief, helpful, slightly playful. Never snarky toward the family — just endearingly eager.

### Technical Decisions

- **Google Auth**: Service account with domain-wide delegation (simplest for family use)
- **Discord Channel**: Bot only responds in `#schedule` (ignores all other channels)
- **Time defaults**: 1-hour duration if no end time is supplied
- **Location support**: Lightweight — include if mentioned, don't prompt for it
- **Calendar event names**: Claude generates them — brief, slightly cute, but informative
- **Current date awareness**: Bot always knows today's date for relative date parsing ("next Friday", "a week from Saturday")

## Output Format

This plan is structured as **tracer code phases**. Each phase ends with a gate check. A Claude Code agent should follow them in order, completing each phase before moving to the next.

## Requirements

- Python 3.11+
- All secrets via environment variables (never hardcoded)
- Async throughout
- Type hints on all functions
- Each phase must end with a working, runnable bot
- Tests for each real implementation
- Interactive Discord buttons (discord.py Views) for confirmations
- All Google Calendar operations go through a single `CalendarService` class
- All natural language parsing goes through a single `NLPService` class (Claude API)

---

## Project Structure

```
schedule-minion/
├── bot/
│   ├── __init__.py
│   ├── main.py                   # Entry point, bot setup
│   ├── config.py                 # Settings from env vars
│   ├── constants.py              # Family mapping, calendar IDs
│   ├── cogs/
│   │   ├── __init__.py
│   │   └── scheduler.py          # All schedule commands + weekly summary
│   ├── services/
│   │   ├── __init__.py
│   │   ├── calendar_service.py   # Google Calendar API wrapper
│   │   └── nlp_service.py        # Claude API for parsing + event naming
│   ├── models/
│   │   ├── __init__.py
│   │   └── events.py             # Data models for parsed intents & events
│   └── views/
│       ├── __init__.py
│       └── confirmations.py      # Discord button views
├── tests/
│   ├── __init__.py
│   ├── conftest.py               # Shared fixtures
│   ├── test_nlp_service.py
│   ├── test_calendar_service.py
│   └── test_scheduler_cog.py
├── .env.example
├── requirements.txt
├── credentials/
│   └── .gitkeep                  # Service account JSON goes here (gitignored)
├── .gitignore
└── README.md
```

---

## Data Models

Define these first — they're the contract between NLP parsing and calendar operations.

**`bot/models/events.py`**:
```python
"""Data models for schedule intents and calendar events."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class IntentType(Enum):
    CREATE = "create"
    QUERY = "query"
    RESCHEDULE = "reschedule"
    DELETE = "delete"
    UNKNOWN = "unknown"


@dataclass
class FamilyMember:
    name: str          # Display name: "Dad", "Mom", "Layla", "Niall"
    email: str         # Gmail address
    calendar_id: str   # Usually same as email for primary calendar


@dataclass
class ParsedIntent:
    """What Claude understood from the user's message."""
    intent: IntentType
    title: str | None = None              # Generated event name (cute but brief)
    start_time: datetime | None = None
    end_time: datetime | None = None
    location: str | None = None
    people: list[FamilyMember] = field(default_factory=list)
    search_query: str | None = None       # For query/reschedule/delete — what to look for
    raw_message: str = ""
    confidence: float = 1.0
    notes: str | None = None              # Any extra context Claude extracted


@dataclass
class CalendarEvent:
    """An event from Google Calendar."""
    event_id: str
    calendar_id: str
    title: str
    start_time: datetime
    end_time: datetime
    location: str | None = None
    attendees: list[str] = field(default_factory=list)  # email addresses

    @property
    def duration_str(self) -> str:
        delta = self.end_time - self.start_time
        hours = delta.seconds // 3600
        minutes = (delta.seconds % 3600) // 60
        if hours and minutes:
            return f"{hours}h {minutes}m"
        elif hours:
            return f"{hours}h"
        return f"{minutes}m"
```

---

## Family Constants

**`bot/constants.py`**:
```python
"""Family member mapping and calendar configuration."""

from bot.models.events import FamilyMember

# Family members — used for NLP parsing and calendar operations
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

# Aliases so Claude can map casual references
NAME_ALIASES: dict[str, str] = {
    "geoff": "dad",
    "daddy": "dad",
    "father": "dad",
    "free": "mom",
    "mama": "mom",
    "mommy": "mom",
    "mother": "mom",
}

# All family members (for "the whole family" default)
ALL_FAMILY = list(FAMILY_MEMBERS.values())
```

---

## Phase 1: Wire the Skeleton (10-15% of effort)

Everything stubbed. Bot starts, connects, listens in `#schedule`, and responds with hardcoded data.

### Step 1.1 — Project Setup

```bash
mkdir schedule-minion && cd schedule-minion
python -m venv venv
source venv/bin/activate
```

**`requirements.txt`**:
```
discord.py>=2.3.0
python-dotenv>=1.0.0
httpx>=0.27.0
anthropic>=0.40.0
google-api-python-client>=2.100.0
google-auth>=2.25.0
google-auth-oauthlib>=1.2.0
pytest>=8.0.0
pytest-asyncio>=0.23.0
python-dateutil>=2.8.0
```

```bash
pip install -r requirements.txt
```

### Step 1.2 — Config

**`bot/config.py`**:
```python
"""Configuration loaded from environment variables."""

from dataclasses import dataclass
import os
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    discord_token: str
    discord_channel_id: int
    anthropic_api_key: str
    google_credentials_path: str
    family_calendar_id: str  # The shared family calendar ID
    timezone: str = "America/Los_Angeles"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            discord_token=os.environ["DISCORD_TOKEN"],
            discord_channel_id=int(os.environ["DISCORD_CHANNEL_ID"]),
            anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
            google_credentials_path=os.environ["GOOGLE_CREDENTIALS_PATH"],
            family_calendar_id=os.environ["FAMILY_CALENDAR_ID"],
        )
```

**`.env.example`**:
```
DISCORD_TOKEN=your-discord-bot-token
DISCORD_CHANNEL_ID=your-schedule-channel-id
ANTHROPIC_API_KEY=your-anthropic-key
GOOGLE_CREDENTIALS_PATH=credentials/service-account.json
FAMILY_CALENDAR_ID=your-shared-family-calendar-id@group.calendar.google.com
```

### Step 1.3 — Stub NLP Service

**`bot/services/nlp_service.py`**:
```python
"""Parses natural language messages into structured intents via Claude API."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from bot.constants import ALL_FAMILY
from bot.models.events import IntentType, ParsedIntent


class NLPService:
    def __init__(self, api_key: str, timezone: str) -> None:
        self.api_key = api_key
        self.timezone = timezone

    async def parse_message(self, message: str) -> ParsedIntent:
        # TODO: Replace with real Claude API call
        now = datetime.now(ZoneInfo(self.timezone))
        return ParsedIntent(
            intent=IntentType.CREATE,
            title="Stubbed Hangout 🎉",
            start_time=now + timedelta(days=1, hours=2),
            end_time=now + timedelta(days=1, hours=3),
            people=ALL_FAMILY,
            raw_message=message,
        )
```

### Step 1.4 — Stub Calendar Service

**`bot/services/calendar_service.py`**:
```python
"""Google Calendar API wrapper."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from bot.models.events import CalendarEvent, FamilyMember


class CalendarService:
    def __init__(self, credentials_path: str, timezone: str) -> None:
        self.credentials_path = credentials_path
        self.timezone = timezone

    async def create_event(
        self,
        calendar_id: str,
        title: str,
        start_time: datetime,
        end_time: datetime,
        attendees: list[FamilyMember] | None = None,
        location: str | None = None,
    ) -> CalendarEvent:
        # TODO: Replace with real Google Calendar API call
        return CalendarEvent(
            event_id="stub-event-id-123",
            calendar_id=calendar_id,
            title=title,
            start_time=start_time,
            end_time=end_time,
            location=location,
            attendees=[m.email for m in (attendees or [])],
        )

    async def get_events(
        self,
        calendar_ids: list[str],
        time_min: datetime,
        time_max: datetime,
    ) -> list[CalendarEvent]:
        # TODO: Replace with real Google Calendar API call
        return []

    async def delete_event(
        self, calendar_id: str, event_id: str
    ) -> bool:
        # TODO: Replace with real API call
        return True

    async def update_event(
        self,
        calendar_id: str,
        event_id: str,
        title: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        location: str | None = None,
    ) -> CalendarEvent:
        # TODO: Replace with real API call
        now = datetime.now(ZoneInfo(self.timezone))
        return CalendarEvent(
            event_id=event_id,
            calendar_id=calendar_id,
            title=title or "Updated Event",
            start_time=start_time or now,
            end_time=end_time or now + timedelta(hours=1),
            location=location,
        )

    async def find_conflicts(
        self,
        calendar_ids: list[str],
        start_time: datetime,
        end_time: datetime,
    ) -> list[CalendarEvent]:
        # TODO: Replace with real conflict check
        return []
```

### Step 1.5 — Confirmation Button Views

**`bot/views/confirmations.py`**:
```python
"""Discord button views for confirming schedule actions."""

from __future__ import annotations

import discord
from typing import Callable, Awaitable


class ConfirmView(discord.ui.View):
    """Generic Yes/No confirmation with callbacks."""

    def __init__(
        self,
        on_confirm: Callable[[], Awaitable[str]],
        on_cancel: Callable[[], Awaitable[str]] | None = None,
        timeout: float = 120.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.on_confirm = on_confirm
        self.on_cancel = on_cancel
        self.value: bool | None = None

    @discord.ui.button(label="Yup!", style=discord.ButtonStyle.green, emoji="✅")
    async def confirm(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.value = True
        result = await self.on_confirm()
        # Disable all buttons after click
        for item in self.children:
            item.disabled = True  # type: ignore[union-attr]
        await interaction.response.edit_message(content=result, view=self)
        self.stop()

    @discord.ui.button(label="Nope", style=discord.ButtonStyle.grey, emoji="❌")
    async def cancel(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.value = False
        result = (
            await self.on_cancel()
            if self.on_cancel
            else "No worries! Schedule Minion stands down. 🫡"
        )
        for item in self.children:
            item.disabled = True  # type: ignore[union-attr]
        await interaction.response.edit_message(content=result, view=self)
        self.stop()

    async def on_timeout(self) -> None:
        self.value = None
```

### Step 1.6 — Scheduler Cog (the big one — stubbed routing)

**`bot/cogs/scheduler.py`**:
```python
"""Scheduler cog: message listener, intent router, and weekly summary."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands, tasks

from bot.config import Settings
from bot.constants import ALL_FAMILY, FAMILY_MEMBERS
from bot.models.events import IntentType, ParsedIntent, CalendarEvent
from bot.services.calendar_service import CalendarService
from bot.services.nlp_service import NLPService
from bot.views.confirmations import ConfirmView

logger = logging.getLogger(__name__)


class SchedulerCog(commands.Cog):
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
        self.weekly_summary.start()

    async def cog_unload(self) -> None:
        self.weekly_summary.cancel()

    # ── Message Listener ─────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        # Ignore messages from bots
        if message.author.bot:
            return

        # Only respond in the designated channel
        if message.channel.id != self.settings.discord_channel_id:
            return

        # Only respond when bot is mentioned
        if self.bot.user not in message.mentions:
            return

        # Strip the mention from the message text
        clean_content = message.content
        for mention in message.mentions:
            clean_content = clean_content.replace(f"<@{mention.id}>", "").strip()
            clean_content = clean_content.replace(f"<@!{mention.id}>", "").strip()

        if not clean_content:
            await message.reply("You rang? Tell me what to schedule! 📋")
            return

        # Parse intent via NLP
        try:
            intent = await self.nlp_service.parse_message(clean_content)
        except Exception as e:
            logger.error(f"NLP parsing failed: {e}")
            await message.reply(
                "My brain glitched for a sec 🤕 — try saying that again?"
            )
            return

        # Route to the right handler
        await self._route_intent(message, intent)

    async def _route_intent(
        self, message: discord.Message, intent: ParsedIntent
    ) -> None:
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
                    "Hmm, I'm not sure what you're asking me to do 🤔 "
                    "Try something like: *'Dinner at Olive Garden Saturday at 6'* "
                    "or *'What's happening this week?'*"
                )

    # ── Intent Handlers ──────────────────────────────────────────────

    async def _handle_create(
        self, message: discord.Message, intent: ParsedIntent
    ) -> None:
        people_str = self._format_people(intent.people)
        time_str = self._format_time(intent.start_time, intent.end_time)
        location_str = f" at {intent.location}" if intent.location else ""

        confirmation_msg = (
            f"To confirm, {people_str} "
            f"{'is' if len(intent.people) == 1 else 'are'} having "
            f"**{intent.title}**{location_str} on {time_str}?"
        )

        # Check for conflicts before confirming
        if intent.start_time and intent.end_time:
            calendar_ids = [p.calendar_id for p in intent.people]
            calendar_ids.append(self.settings.family_calendar_id)
            conflicts = await self.calendar_service.find_conflicts(
                calendar_ids=calendar_ids,
                start_time=intent.start_time,
                end_time=intent.end_time,
            )
            if conflicts:
                conflict_str = "\n".join(
                    f"  ⚠️ **{c.title}** ({self._format_time(c.start_time, c.end_time)})"
                    for c in conflicts
                )
                confirmation_msg += f"\n\n🔮 **Heads up — possible conflicts:**\n{conflict_str}"

        async def on_confirm() -> str:
            try:
                event = await self.calendar_service.create_event(
                    calendar_id=self.settings.family_calendar_id,
                    title=intent.title or "Family Event",
                    start_time=intent.start_time,
                    end_time=intent.end_time,
                    attendees=intent.people,
                    location=intent.location,
                )
                return (
                    f"✅ Done! **{event.title}** is on the books. "
                    f"Schedule Minion has served. 🫡"
                )
            except Exception as e:
                logger.error(f"Failed to create event: {e}")
                return "😵 Something went wrong creating the event. Try again?"

        view = ConfirmView(on_confirm=on_confirm)
        await message.reply(confirmation_msg, view=view)

    async def _handle_query(
        self, message: discord.Message, intent: ParsedIntent
    ) -> None:
        if not intent.start_time:
            await message.reply(
                "When are you asking about? Try: *'What's happening this Friday?'*"
            )
            return

        # Default query range: full day if no end time
        time_min = intent.start_time
        time_max = intent.end_time or (
            intent.start_time.replace(hour=23, minute=59, second=59)
        )

        calendar_ids = [p.calendar_id for p in intent.people]
        calendar_ids.append(self.settings.family_calendar_id)

        events = await self.calendar_service.get_events(
            calendar_ids=calendar_ids,
            time_min=time_min,
            time_max=time_max,
        )

        if not events:
            date_str = intent.start_time.strftime("%A, %B %-d")
            await message.reply(
                f"Nothing scheduled for {date_str} yet! "
                f"Wide open — the world is your oyster 🦪"
            )
            return

        event_lines = "\n".join(
            f"• **{e.title}** — {self._format_time(e.start_time, e.end_time)}"
            + (f" 📍 {e.location}" if e.location else "")
            for e in sorted(events, key=lambda e: e.start_time)
        )
        date_str = intent.start_time.strftime("%A, %B %-d")
        people_str = self._format_people(intent.people)
        await message.reply(
            f"Here's what {people_str} {'has' if len(intent.people) == 1 else 'have'} "
            f"going on {date_str}:\n\n{event_lines}"
        )

    async def _handle_reschedule(
        self, message: discord.Message, intent: ParsedIntent
    ) -> None:
        if not intent.search_query:
            await message.reply(
                "Which event should I reschedule? "
                "Try: *'Move Layla's dentist to next Thursday at 3'*"
            )
            return

        # Find the event to reschedule
        now = datetime.now(ZoneInfo(self.settings.timezone))
        events = await self.calendar_service.get_events(
            calendar_ids=[self.settings.family_calendar_id]
                + [m.calendar_id for m in ALL_FAMILY],
            time_min=now,
            time_max=now + timedelta(days=90),
        )

        # Simple title match (Claude provides search_query)
        matching = [
            e for e in events
            if intent.search_query.lower() in e.title.lower()
        ]

        if not matching:
            await message.reply(
                f"I couldn't find anything matching **{intent.search_query}** "
                f"on the calendar 🔍"
            )
            return

        target = matching[0]  # Take the nearest match
        time_str = self._format_time(intent.start_time, intent.end_time)

        confirmation_msg = (
            f"Move **{target.title}** to {time_str}?"
        )

        async def on_confirm() -> str:
            try:
                await self.calendar_service.update_event(
                    calendar_id=target.calendar_id,
                    event_id=target.event_id,
                    start_time=intent.start_time,
                    end_time=intent.end_time,
                )
                return f"✅ **{target.title}** has been rescheduled. Your minion delivers. 📋"
            except Exception as e:
                logger.error(f"Failed to reschedule: {e}")
                return "😵 Couldn't reschedule that one. Try again?"

        view = ConfirmView(on_confirm=on_confirm)
        await message.reply(confirmation_msg, view=view)

    async def _handle_delete(
        self, message: discord.Message, intent: ParsedIntent
    ) -> None:
        if not intent.search_query:
            await message.reply(
                "Which event should I cancel? "
                "Try: *'Cancel the dentist appointment'*"
            )
            return

        now = datetime.now(ZoneInfo(self.settings.timezone))
        events = await self.calendar_service.get_events(
            calendar_ids=[self.settings.family_calendar_id]
                + [m.calendar_id for m in ALL_FAMILY],
            time_min=now,
            time_max=now + timedelta(days=90),
        )

        matching = [
            e for e in events
            if intent.search_query.lower() in e.title.lower()
        ]

        if not matching:
            await message.reply(
                f"Couldn't find **{intent.search_query}** on the calendar 🔍"
            )
            return

        target = matching[0]

        async def on_confirm() -> str:
            try:
                await self.calendar_service.delete_event(
                    calendar_id=target.calendar_id,
                    event_id=target.event_id,
                )
                return f"🗑️ **{target.title}** has been banished from the calendar."
            except Exception as e:
                logger.error(f"Failed to delete: {e}")
                return "😵 Couldn't delete that one. Try again?"

        view = ConfirmView(on_confirm=on_confirm)
        await message.reply(
            f"Cancel **{target.title}** "
            f"({self._format_time(target.start_time, target.end_time)})? "
            f"This can't be undone!",
            view=view,
        )

    # ── Weekly Summary ───────────────────────────────────────────────

    @tasks.loop(
        time=datetime.time(hour=18, minute=0)  # Will be refined in Phase 2
    )
    async def weekly_summary(self) -> None:
        now = datetime.now(ZoneInfo(self.settings.timezone))
        if now.weekday() != 6:  # Only Sunday
            return

        channel = self.bot.get_channel(self.settings.discord_channel_id)
        if channel is None:
            return

        # Get next 7 days of events
        week_start = now + timedelta(days=1)
        week_end = week_start + timedelta(days=7)

        calendar_ids = [self.settings.family_calendar_id] + [
            m.calendar_id for m in ALL_FAMILY
        ]
        events = await self.calendar_service.get_events(
            calendar_ids=calendar_ids,
            time_min=week_start,
            time_max=week_end,
        )

        if not events:
            await channel.send(
                "📋 **Weekly Briefing**\n\n"
                "Nothing on the books this week! "
                "The Minion awaits your commands. 🫡"
            )
            return

        events.sort(key=lambda e: e.start_time)

        # Group by day
        days: dict[str, list[CalendarEvent]] = {}
        for event in events:
            day_key = event.start_time.strftime("%A, %B %-d")
            days.setdefault(day_key, []).append(event)

        summary_lines = []
        for day, day_events in days.items():
            summary_lines.append(f"\n**{day}**")
            for e in day_events:
                time_str = e.start_time.strftime("%-I:%M %p")
                loc = f" 📍 {e.location}" if e.location else ""
                summary_lines.append(f"  • {time_str} — **{e.title}**{loc}")

        summary = "\n".join(summary_lines)
        await channel.send(
            f"📋 **Weekly Briefing — Here's what's coming up!**\n{summary}\n\n"
            f"*Your faithful Minion is standing by for changes.* 🫡"
        )

    @weekly_summary.before_loop
    async def before_weekly_summary(self) -> None:
        await self.bot.wait_until_ready()

    # ── Formatting Helpers ───────────────────────────────────────────

    @staticmethod
    def _format_people(people: list) -> str:
        if len(people) == len(ALL_FAMILY):
            return "the whole family"
        names = [p.name for p in people]
        if len(names) == 1:
            return names[0]
        return ", ".join(names[:-1]) + f" and {names[-1]}"

    @staticmethod
    def _format_time(
        start: datetime | None, end: datetime | None
    ) -> str:
        if not start:
            return "TBD"
        date_str = start.strftime("%A, %B %-d")
        start_str = start.strftime("%-I:%M %p")
        if end and end.date() == start.date():
            end_str = end.strftime("%-I:%M %p")
            return f"{date_str} from {start_str} to {end_str}"
        return f"{date_str} at {start_str}"
```

### Step 1.7 — Entry Point

**`bot/main.py`**:
```python
"""Bot entry point."""

import asyncio
import logging

import discord
from discord.ext import commands

from bot.config import Settings
from bot.cogs.scheduler import SchedulerCog
from bot.services.calendar_service import CalendarService
from bot.services.nlp_service import NLPService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def setup_bot() -> commands.Bot:
    settings = Settings.from_env()

    intents = discord.Intents.default()
    intents.message_content = True
    bot = commands.Bot(command_prefix="!", intents=intents)

    calendar_service = CalendarService(
        credentials_path=settings.google_credentials_path,
        timezone=settings.timezone,
    )
    nlp_service = NLPService(
        api_key=settings.anthropic_api_key,
        timezone=settings.timezone,
    )

    @bot.event
    async def on_ready() -> None:
        logger.info(f"📋 {bot.user} is online and ready to serve!")

    await bot.add_cog(
        SchedulerCog(bot, settings, calendar_service, nlp_service)
    )

    return bot


def main() -> None:
    async def run() -> None:
        bot = await setup_bot()
        settings = Settings.from_env()
        await bot.start(settings.discord_token)

    asyncio.run(run())


if __name__ == "__main__":
    main()
```

### Step 1.8 — Smoke Tests

**`tests/conftest.py`**:
```python
"""Shared test fixtures."""

import pytest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from bot.models.events import CalendarEvent, ParsedIntent, IntentType, FamilyMember
from bot.constants import ALL_FAMILY

TZ = ZoneInfo("America/Los_Angeles")


@pytest.fixture
def sample_weather_intent() -> ParsedIntent:
    now = datetime.now(TZ)
    return ParsedIntent(
        intent=IntentType.CREATE,
        title="Jimmy Hang Outs 🎉",
        start_time=now + timedelta(days=7),
        end_time=now + timedelta(days=7, hours=1),
        people=ALL_FAMILY,
        raw_message="We're hanging out with Jimmy at 1 pm a week from Saturday",
    )


@pytest.fixture
def sample_event() -> CalendarEvent:
    now = datetime.now(TZ)
    return CalendarEvent(
        event_id="test-123",
        calendar_id="family@group.calendar.google.com",
        title="Date Night ❤️",
        start_time=now + timedelta(days=3),
        end_time=now + timedelta(days=3, hours=3),
        attendees=["Geoffe.gallinger@gmail.com", "Freelalala@gmail.com"],
    )
```

**`tests/test_nlp_service.py`**:
```python
"""Smoke tests for NLP service."""

import pytest
from bot.services.nlp_service import NLPService
from bot.models.events import IntentType


@pytest.mark.asyncio
async def test_parse_message_returns_parsed_intent():
    service = NLPService(api_key="fake-key", timezone="America/Los_Angeles")
    intent = await service.parse_message("Dinner at 6 on Friday")
    assert intent.intent == IntentType.CREATE
    assert intent.title is not None
    assert intent.start_time is not None
```

**`tests/test_calendar_service.py`**:
```python
"""Smoke tests for calendar service."""

import pytest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from bot.services.calendar_service import CalendarService
from bot.constants import ALL_FAMILY

TZ = ZoneInfo("America/Los_Angeles")


@pytest.mark.asyncio
async def test_create_event_returns_calendar_event():
    service = CalendarService(
        credentials_path="fake-path.json", timezone="America/Los_Angeles"
    )
    now = datetime.now(TZ)
    event = await service.create_event(
        calendar_id="test@group.calendar.google.com",
        title="Test Event",
        start_time=now,
        end_time=now + timedelta(hours=1),
        attendees=ALL_FAMILY,
    )
    assert event.event_id is not None
    assert event.title == "Test Event"


@pytest.mark.asyncio
async def test_get_events_returns_list():
    service = CalendarService(
        credentials_path="fake-path.json", timezone="America/Los_Angeles"
    )
    now = datetime.now(TZ)
    events = await service.get_events(
        calendar_ids=["test@group.calendar.google.com"],
        time_min=now,
        time_max=now + timedelta(days=7),
    )
    assert isinstance(events, list)
```

### ✅ Gate Check — Phase 1

```bash
pytest tests/ -v
```

All tests pass. Bot starts, connects to Discord, listens for `@Schedule Minion` mentions in `#schedule`, parses intent (stubbed), and responds with confirmation buttons. **You have a demoable skeleton.**

---

## Phase 2: Replace Stubs with Real Implementations

| Priority | Feature | Why |
|----------|---------|-----|
| **P0** | NLP Service (Claude API) | Everything depends on understanding what the user said |
| **P0** | Calendar Service (Google API) | Core CRUD — the bot's reason for existing |
| **P1** | Conflict detection (real) | High-value safety net for family scheduling |
| **P1** | Weekly summary timing (precise Sunday 6 PM) | Must fire reliably |
| **P2** | Error handling + retries | Resilience for daily family use |
| **P3** | Edge cases (multi-day events, recurring events) | Nice-to-haves |

### P0-A: Real NLP Service (Claude API)

Replace the stub in **`bot/services/nlp_service.py`**:

```python
"""Parses natural language messages into structured intents via Claude API."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import anthropic

from bot.constants import ALL_FAMILY, FAMILY_MEMBERS, NAME_ALIASES
from bot.models.events import FamilyMember, IntentType, ParsedIntent

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are the brain of a family Discord bot called "Schedule Minion." Your job is \
to parse natural language messages about scheduling into structured JSON.

## Family Members
- Dad (Geoff) — Geoffe.gallinger@gmail.com
- Mom (Free) — Freelalala@gmail.com
- Layla — One.Bad.Baldie@gmail.com
- Niall — ANiallation@gmail.com

## Rules
1. Determine the intent: "create", "query", "reschedule", "delete", or "unknown"
2. For CREATE intents:
   - Generate a short, cute event title (2-4 words max). Be a little playful. \
Examples: "Jimmy Hang Outs", "Pizza Night 🍕", "Layla's Sleepover Bash", \
"Dentist Doom 🦷", "Soccer Practice ⚽"
   - Parse start time and end time. Default to 1 hour duration if no end time given.
   - If no people are mentioned, assume the WHOLE FAMILY.
   - Extract location if mentioned.
3. For QUERY intents:
   - Parse the time range being asked about.
   - Identify which people are being asked about (default: whole family).
4. For RESCHEDULE intents:
   - Include search_query (name of event to find) AND the new time.
5. For DELETE intents:
   - Include search_query (name of event to find).
6. Use the family member names/aliases to identify people. "We" means the whole family.

## Output Format
Respond with ONLY valid JSON, no markdown, no explanation:
{
  "intent": "create" | "query" | "reschedule" | "delete" | "unknown",
  "title": "Event Name" | null,
  "start_time": "ISO 8601 datetime" | null,
  "end_time": "ISO 8601 datetime" | null,
  "location": "string" | null,
  "people": ["dad", "mom", "layla", "niall"] | [],
  "search_query": "string to match event title" | null,
  "notes": "any extra context" | null
}

IMPORTANT: If people is empty or not specified, it means the whole family.
"""


class NLPService:
    def __init__(self, api_key: str, timezone: str) -> None:
        self.client = anthropic.AsyncAnthropic(api_key=api_key)
        self.timezone = timezone

    async def parse_message(self, message: str) -> ParsedIntent:
        now = datetime.now(ZoneInfo(self.timezone))
        user_prompt = (
            f"Current date and time: {now.strftime('%A, %B %d, %Y at %I:%M %p %Z')}\n"
            f"Timezone: {self.timezone}\n\n"
            f"User message: {message}"
        )

        response = await self.client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=500,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )

        raw_text = response.content[0].text.strip()

        # Strip markdown code fences if Claude adds them
        if raw_text.startswith("```"):
            raw_text = raw_text.split("\n", 1)[1]
            if raw_text.endswith("```"):
                raw_text = raw_text[:-3]
            raw_text = raw_text.strip()

        data = json.loads(raw_text)

        # Resolve people
        people = self._resolve_people(data.get("people", []))

        # Parse times
        start_time = (
            datetime.fromisoformat(data["start_time"])
            if data.get("start_time")
            else None
        )
        end_time = (
            datetime.fromisoformat(data["end_time"])
            if data.get("end_time")
            else None
        )

        return ParsedIntent(
            intent=IntentType(data["intent"]),
            title=data.get("title"),
            start_time=start_time,
            end_time=end_time,
            location=data.get("location"),
            people=people,
            search_query=data.get("search_query"),
            raw_message=message,
            notes=data.get("notes"),
        )

    def _resolve_people(self, names: list[str]) -> list[FamilyMember]:
        if not names:
            return list(ALL_FAMILY)

        people = []
        for name in names:
            key = name.lower()
            # Check aliases first
            if key in NAME_ALIASES:
                key = NAME_ALIASES[key]
            if key in FAMILY_MEMBERS:
                people.append(FAMILY_MEMBERS[key])

        return people if people else list(ALL_FAMILY)
```

**Why this prompt works (6-component analysis)**:

| Component | Implementation |
|-----------|---------------|
| **Role** | "Brain of a family Discord bot called Schedule Minion" |
| **Goal** | "Parse natural language into structured JSON" with 5 intent types |
| **Context** | Family member table with names, aliases, emails. Current date/time injected per-call |
| **Format** | Exact JSON schema specified with all fields and types |
| **Examples** | Cute event name examples: "Pizza Night 🍕", "Dentist Doom 🦷" |
| **Constraints** | Default 1hr duration, empty people = whole family, ONLY valid JSON output |

**Test** — update `tests/test_nlp_service.py`:
```python
@pytest.mark.asyncio
async def test_parse_create_intent():
    """Mock-based test for NLP parsing."""
    from unittest.mock import AsyncMock, MagicMock, patch

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps({
        "intent": "create",
        "title": "Jimmy Hang Outs 🎉",
        "start_time": "2026-03-07T13:00:00-08:00",
        "end_time": "2026-03-07T14:00:00-08:00",
        "location": None,
        "people": [],
        "search_query": None,
        "notes": None,
    }))]

    with patch("bot.services.nlp_service.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = AsyncMock()
        mock_client.messages.create.return_value = mock_response
        mock_cls.return_value = mock_client

        service = NLPService(api_key="fake", timezone="America/Los_Angeles")
        service.client = mock_client

        intent = await service.parse_message(
            "We're hanging out with Jimmy at 1 pm a week from Saturday"
        )

        assert intent.intent == IntentType.CREATE
        assert "Jimmy" in intent.title
        assert len(intent.people) == 4  # whole family
```

**Gate check**: `pytest` passes. Bot now understands natural language.

---

### P0-B: Real Calendar Service (Google Calendar API)

Replace the stub in **`bot/services/calendar_service.py`**:

```python
"""Google Calendar API wrapper."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from functools import partial

from google.oauth2 import service_account
from googleapiclient.discovery import build

from bot.models.events import CalendarEvent, FamilyMember

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar"]


class CalendarService:
    def __init__(self, credentials_path: str, timezone: str) -> None:
        self.timezone = timezone
        credentials = service_account.Credentials.from_service_account_file(
            credentials_path, scopes=SCOPES
        )
        self._service = build("calendar", "v3", credentials=credentials)

    def _run_sync(self, func, *args, **kwargs):
        """Run synchronous Google API calls in a thread pool."""
        loop = asyncio.get_event_loop()
        return loop.run_in_executor(None, partial(func, *args, **kwargs))

    async def create_event(
        self,
        calendar_id: str,
        title: str,
        start_time: datetime,
        end_time: datetime,
        attendees: list[FamilyMember] | None = None,
        location: str | None = None,
    ) -> CalendarEvent:
        event_body = {
            "summary": title,
            "start": {
                "dateTime": start_time.isoformat(),
                "timeZone": self.timezone,
            },
            "end": {
                "dateTime": end_time.isoformat(),
                "timeZone": self.timezone,
            },
        }

        if location:
            event_body["location"] = location

        if attendees:
            event_body["attendees"] = [
                {"email": m.email} for m in attendees
            ]

        result = await self._run_sync(
            self._service.events()
            .insert(calendarId=calendar_id, body=event_body)
            .execute
        )

        return CalendarEvent(
            event_id=result["id"],
            calendar_id=calendar_id,
            title=result["summary"],
            start_time=start_time,
            end_time=end_time,
            location=location,
            attendees=[m.email for m in (attendees or [])],
        )

    async def get_events(
        self,
        calendar_ids: list[str],
        time_min: datetime,
        time_max: datetime,
    ) -> list[CalendarEvent]:
        all_events: list[CalendarEvent] = []
        seen_ids: set[str] = set()  # Deduplicate across calendars

        for cal_id in calendar_ids:
            try:
                result = await self._run_sync(
                    self._service.events()
                    .list(
                        calendarId=cal_id,
                        timeMin=time_min.isoformat(),
                        timeMax=time_max.isoformat(),
                        singleEvents=True,
                        orderBy="startTime",
                    )
                    .execute
                )

                for item in result.get("items", []):
                    if item["id"] in seen_ids:
                        continue
                    seen_ids.add(item["id"])

                    start = item["start"].get("dateTime", item["start"].get("date"))
                    end = item["end"].get("dateTime", item["end"].get("date"))

                    all_events.append(
                        CalendarEvent(
                            event_id=item["id"],
                            calendar_id=cal_id,
                            title=item.get("summary", "Untitled"),
                            start_time=datetime.fromisoformat(start),
                            end_time=datetime.fromisoformat(end),
                            location=item.get("location"),
                            attendees=[
                                a["email"]
                                for a in item.get("attendees", [])
                            ],
                        )
                    )
            except Exception as e:
                logger.error(f"Failed to fetch events from {cal_id}: {e}")

        return sorted(all_events, key=lambda e: e.start_time)

    async def delete_event(self, calendar_id: str, event_id: str) -> bool:
        try:
            await self._run_sync(
                self._service.events()
                .delete(calendarId=calendar_id, eventId=event_id)
                .execute
            )
            return True
        except Exception as e:
            logger.error(f"Failed to delete event {event_id}: {e}")
            return False

    async def update_event(
        self,
        calendar_id: str,
        event_id: str,
        title: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        location: str | None = None,
    ) -> CalendarEvent:
        # Fetch existing event first
        existing = await self._run_sync(
            self._service.events()
            .get(calendarId=calendar_id, eventId=event_id)
            .execute
        )

        if title:
            existing["summary"] = title
        if start_time:
            existing["start"] = {
                "dateTime": start_time.isoformat(),
                "timeZone": self.timezone,
            }
        if end_time:
            existing["end"] = {
                "dateTime": end_time.isoformat(),
                "timeZone": self.timezone,
            }
        if location:
            existing["location"] = location

        result = await self._run_sync(
            self._service.events()
            .update(calendarId=calendar_id, eventId=event_id, body=existing)
            .execute
        )

        return CalendarEvent(
            event_id=result["id"],
            calendar_id=calendar_id,
            title=result.get("summary", "Untitled"),
            start_time=start_time
            or datetime.fromisoformat(
                result["start"].get("dateTime", result["start"]["date"])
            ),
            end_time=end_time
            or datetime.fromisoformat(
                result["end"].get("dateTime", result["end"]["date"])
            ),
            location=result.get("location"),
        )

    async def find_conflicts(
        self,
        calendar_ids: list[str],
        start_time: datetime,
        end_time: datetime,
    ) -> list[CalendarEvent]:
        """Find events that overlap with the proposed time window."""
        existing = await self.get_events(
            calendar_ids=calendar_ids,
            time_min=start_time,
            time_max=end_time,
        )
        return existing  # Any event in this window is a conflict
```

**Gate check**: `pytest` passes. Bot creates, queries, updates, and deletes real Google Calendar events.

---

### P1-A: Precise Weekly Summary Timing

Update the `weekly_summary` task in **`bot/cogs/scheduler.py`**:

```python
import datetime as dt
from zoneinfo import ZoneInfo

@tasks.loop(
    time=dt.time(hour=18, minute=0, tzinfo=ZoneInfo("America/Los_Angeles"))
)
async def weekly_summary(self) -> None:
    now = datetime.now(ZoneInfo(self.settings.timezone))
    if now.weekday() != 6:  # Only fire on Sundays
        return
    # ... rest of the method stays the same
```

---

### P2: Error Handling

Add to **`bot/cogs/scheduler.py`**:

```python
@commands.Cog.listener()
async def on_message(self, message: discord.Message) -> None:
    # ... existing checks ...

    try:
        intent = await self.nlp_service.parse_message(clean_content)
    except json.JSONDecodeError:
        await message.reply(
            "I got a little confused parsing that 🤕 — could you rephrase?"
        )
        return
    except anthropic.APIError as e:
        logger.error(f"Claude API error: {e}")
        await message.reply(
            "My brain is taking a nap 😴 — try again in a moment?"
        )
        return
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        await message.reply(
            "Something unexpected happened! The Minion is confused 🤕"
        )
        return
```

---

## Phase 3: Polish

- [ ] Add `README.md` with Google Cloud service account setup instructions
- [ ] Add a `/help` message the bot responds with when mentioned with no actionable text
- [ ] Deduplicate events across shared + individual calendars in query results
- [ ] Handle all-day events in formatting (no time display)
- [ ] Add rate limiting awareness (Google Calendar has a 1M queries/day free tier — not a real concern for family use, but good to log)
- [ ] Handle edge case: user mentions bot but message is just emoji or a reaction
- [ ] Add `conftest.py` fixture for mocking the Google Calendar service
- [ ] Test confirmation button flows with mock interactions

---

## Google Cloud Service Account Setup Checklist

1. Go to https://console.cloud.google.com
2. Create a new project (or use an existing one)
3. Enable the **Google Calendar API**
4. Go to **IAM & Admin → Service Accounts** → Create Service Account
5. Name it "schedule-minion", grant no special roles
6. Create a key (JSON) → download to `credentials/service-account.json`
7. Copy the service account email (e.g., `schedule-minion@project.iam.gserviceaccount.com`)
8. **Share each family calendar** with the service account email:
   - Open Google Calendar → Settings → specific calendar → Share with specific people
   - Add the service account email with **"Make changes to events"** permission
   - Do this for the shared family calendar AND each person's individual calendar
9. Get the family calendar ID from Settings → Integrate calendar → Calendar ID
10. Put it all in `.env`

## Discord Bot Setup Checklist

1. Go to https://discord.com/developers/applications
2. Create "Schedule Minion"
3. **Bot** tab → Add Bot → copy token → `.env`
4. Enable **MESSAGE CONTENT** intent (Privileged Gateway Intents)
5. **OAuth2 → URL Generator**:
   - Scopes: `bot`
   - Bot Permissions: `Send Messages`, `Read Message History`, `Embed Links`
6. Invite to your server
7. Create a `#schedule` channel → copy Channel ID → `.env`

---

## Key Concepts for Learning

| Concept | Where it appears |
|---------|-----------------|
| **Structured Output from LLMs** | NLP service forces Claude to return JSON — a critical production pattern for AI apps |
| **Async wrapping of sync libs** | `run_in_executor` wraps Google's synchronous SDK for use in async Discord.py |
| **Intent-based routing** | `_route_intent` uses pattern matching to dispatch to handlers — cleaner than if/elif chains |
| **Interactive UI (Views)** | `ConfirmView` uses Discord.py's component system — buttons with async callbacks |
| **Deduplication** | Calendar queries use `seen_ids` to avoid showing the same event from shared + individual calendars |
| **Service account auth** | No OAuth flow needed — service accounts are ideal for server-to-server trusted environments |
| **Prompt Engineering** | The NLP system prompt uses all 6 components: role, goal (intent types), context (family table + current time), format (JSON schema), examples (cute event names), constraints (default behaviors) |
| **Tracer Code** | Phase 1 gives you a bot that responds to mentions with stubbed data. Each P0/P1 replaces exactly one stub. Always demoable. |

---

## Running the Bot

```bash
# 1. Setup
cp .env.example .env
# Fill in all keys and IDs

# 2. Install
pip install -r requirements.txt

# 3. Test
pytest tests/ -v

# 4. Run
python -m bot.main
```

---

## Example Interactions

```
User: @Schedule Minion We're hanging out with Jimmy at 1 pm a week from Saturday
Bot:  To confirm, the whole family is having **Jimmy Hang Outs 🎉** on
      Saturday, March 7th from 1:00 PM to 2:00 PM?
      [✅ Yup!] [❌ Nope]

User: clicks ✅
Bot:  ✅ Done! **Jimmy Hang Outs 🎉** is on the books. Schedule Minion has served. 🫡

User: @Schedule Minion What have we got going on this Wednesday?
Bot:  Here's what the whole family has going on Wednesday, March 4th:
        • 1:00 PM — **Jimmy Hang Outs 🎉**
        • 6:00 PM — **Soccer Practice ⚽** 📍 Willow Glen Fields

User: @Schedule Minion Is Layla free for a sleepover next Friday?
Bot:  Here's what Layla has going on Friday, March 6th:
        Nothing on Layla's schedule! But heads up — Mom and Dad have
        **Date Night ❤️** that evening. Sounds like good sleepover timing!

User: @Schedule Minion Cancel the Jimmy hangout
Bot:  Cancel **Jimmy Hang Outs 🎉** (Saturday, March 7th from 1:00 PM to 2:00 PM)?
      This can't be undone!
      [✅ Yup!] [❌ Nope]

User: @Schedule Minion Move soccer practice to Thursday at 4
Bot:  Move **Soccer Practice ⚽** to Thursday, March 5th at 4:00 PM?
      [✅ Yup!] [❌ Nope]
```
