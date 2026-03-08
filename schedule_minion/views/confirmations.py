"""Discord button views for confirming schedule actions."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


class ConfirmView(discord.ui.View):
    """Generic Yes/No confirmation with async callbacks."""

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

    @discord.ui.button(label="Yup!", style=discord.ButtonStyle.green, emoji="\u2705")
    async def confirm(
        self, interaction: discord.Interaction, button: discord.ui.Button[ConfirmView]
    ) -> None:
        """Handle confirmation button click."""
        self.value = True
        result = await self.on_confirm()
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        await interaction.response.edit_message(content=result, view=self)
        self.stop()

    @discord.ui.button(label="Nope", style=discord.ButtonStyle.grey, emoji="\u274c")
    async def cancel(
        self, interaction: discord.Interaction, button: discord.ui.Button[ConfirmView]
    ) -> None:
        """Handle cancellation button click."""
        self.value = False
        if self.on_cancel:
            result = await self.on_cancel()
        else:
            result = "No worries! Schedule Minion stands down."
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        await interaction.response.edit_message(content=result, view=self)
        self.stop()

    async def on_timeout(self) -> None:
        """Handle view timeout."""
        self.value = None
