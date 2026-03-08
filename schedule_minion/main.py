"""Bot entry point for schedule-minion."""

from __future__ import annotations

import asyncio
import logging
import signal

import discord
from discord.ext import commands
from dotenv import load_dotenv

from schedule_minion.cogs.scheduler import SchedulerCog
from schedule_minion.config import Settings
from schedule_minion.services.calendar_service import CalendarService
from schedule_minion.services.nlp_service import NLPService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def setup_bot() -> commands.Bot:
    """Create and configure the Discord bot."""
    load_dotenv()
    settings = Settings.from_env()

    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True
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
        logger.info("%s is online and ready to serve!", bot.user)

    await bot.add_cog(SchedulerCog(bot, settings, calendar_service, nlp_service))

    return bot


def main() -> None:
    """Run the Schedule Minion bot."""

    async def run() -> None:
        bot = await setup_bot()
        settings = Settings.from_env()

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(
                sig,
                lambda: asyncio.ensure_future(_shutdown(bot)),
            )

        await bot.start(settings.discord_token)

    asyncio.run(run())


async def _shutdown(bot: commands.Bot) -> None:
    """Gracefully shut down the bot on SIGTERM/SIGINT."""
    logger.info("Received shutdown signal, closing bot...")
    await bot.close()


if __name__ == "__main__":
    main()
