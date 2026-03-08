"""Tests for schedule_minion.views.confirmations module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from schedule_minion.views.confirmations import ConfirmView


class TestConfirmView:
    """Tests for the confirmation button view."""

    def test_creates_with_callback(self) -> None:
        async def on_confirm() -> str:
            return "confirmed"

        view = ConfirmView(on_confirm=on_confirm)
        assert view.on_confirm is on_confirm
        assert view.value is None

    def test_default_timeout(self) -> None:
        async def on_confirm() -> str:
            return "done"

        view = ConfirmView(on_confirm=on_confirm)
        assert view.timeout == 120.0

    def test_custom_timeout(self) -> None:
        async def on_confirm() -> str:
            return "done"

        view = ConfirmView(on_confirm=on_confirm, timeout=60.0)
        assert view.timeout == 60.0

    def test_optional_cancel_callback(self) -> None:
        async def on_confirm() -> str:
            return "done"

        view = ConfirmView(on_confirm=on_confirm)
        assert view.on_cancel is None

    def test_with_cancel_callback(self) -> None:
        async def on_confirm() -> str:
            return "confirmed"

        async def on_cancel() -> str:
            return "cancelled"

        view = ConfirmView(on_confirm=on_confirm, on_cancel=on_cancel)
        assert view.on_cancel is on_cancel

    @pytest.mark.asyncio
    async def test_on_timeout_sets_value_to_none(self) -> None:
        async def on_confirm() -> str:
            return "done"

        view = ConfirmView(on_confirm=on_confirm)
        await view.on_timeout()
        assert view.value is None

    @pytest.mark.asyncio
    async def test_confirm_sets_value_true(self) -> None:
        on_confirm = AsyncMock(return_value="Event created!")
        view = ConfirmView(on_confirm=on_confirm)

        interaction = MagicMock(spec=discord.Interaction)
        interaction.response = MagicMock()
        interaction.response.edit_message = AsyncMock()

        with patch.object(view, "stop"):
            await view.confirm.callback(interaction)

        assert view.value is True
        on_confirm.assert_awaited_once()
        interaction.response.edit_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cancel_sets_value_false_default_message(self) -> None:
        on_confirm = AsyncMock(return_value="done")
        view = ConfirmView(on_confirm=on_confirm)

        interaction = MagicMock(spec=discord.Interaction)
        interaction.response = MagicMock()
        interaction.response.edit_message = AsyncMock()

        with patch.object(view, "stop"):
            await view.cancel.callback(interaction)

        assert view.value is False
        interaction.response.edit_message.assert_awaited_once()
        call_kwargs = interaction.response.edit_message.call_args
        content = call_kwargs.kwargs.get("content", "")
        assert "stands down" in content

    @pytest.mark.asyncio
    async def test_cancel_uses_custom_callback(self) -> None:
        on_confirm = AsyncMock(return_value="done")
        on_cancel = AsyncMock(return_value="Custom cancel message")
        view = ConfirmView(on_confirm=on_confirm, on_cancel=on_cancel)

        interaction = MagicMock(spec=discord.Interaction)
        interaction.response = MagicMock()
        interaction.response.edit_message = AsyncMock()

        with patch.object(view, "stop"):
            await view.cancel.callback(interaction)

        on_cancel.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_confirm_disables_buttons(self) -> None:
        on_confirm = AsyncMock(return_value="Done!")
        view = ConfirmView(on_confirm=on_confirm)

        interaction = MagicMock(spec=discord.Interaction)
        interaction.response = MagicMock()
        interaction.response.edit_message = AsyncMock()

        with patch.object(view, "stop"):
            await view.confirm.callback(interaction)

        for item in view.children:
            if isinstance(item, discord.ui.Button):
                assert item.disabled is True
