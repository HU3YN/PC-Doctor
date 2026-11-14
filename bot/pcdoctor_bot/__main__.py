"""The Discord side of the bot. Kept thin: the rules live in core.py.

Run with:  python -m pcdoctor_bot
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

import discord
import httpx
from discord import app_commands

from . import core

log = logging.getLogger("pcdoctor_bot")

# Never ping anyone, whatever the text says.
NO_MENTIONS = discord.AllowedMentions.none()

# Uploads are held on disk or in memory while they are checked, so only a
# couple run at once.
MAX_CONCURRENT_RUNS = 2


class DoctorBot(discord.Client):
    def __init__(self, settings: core.Settings) -> None:
        # Only the "guilds" intent: enough to notice being added to a server.
        # No message content, no members, no presences.
        intents = discord.Intents.none()
        intents.guilds = True
        super().__init__(intents=intents, allowed_mentions=NO_MENTIONS)
        self.settings = settings
        self.tree = app_commands.CommandTree(self)
        self.cooldown = core.Cooldown(settings.cooldown_seconds)
        self.slots = asyncio.Semaphore(MAX_CONCURRENT_RUNS)
        self.http_client: httpx.AsyncClient | None = None

    async def setup_hook(self) -> None:
        self.http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(120.0, connect=10.0), follow_redirects=False
        )
        guilds = [discord.Object(id=guild_id) for guild_id in sorted(self.settings.guild_ids)]
        self.tree.add_command(diagnose, guilds=guilds)
        # Register the command in the approved servers only - never globally.
        for guild in guilds:
            try:
                await self.tree.sync(guild=guild)
            except discord.HTTPException:
                # Usually: the bot has not been added to that server yet.
                log.warning("Could not register /diagnose in server %s.", guild.id)

    async def close(self) -> None:
        if self.http_client is not None:
            await self.http_client.aclose()
        await super().close()

    async def on_ready(self) -> None:
        log.info("Connected. In %d server(s).", len(self.guilds))
        # Leave servers the bot was added to while it was offline.
        for guild in list(self.guilds):
            await self.leave_if_not_allowed(guild)

    async def on_guild_join(self, guild: discord.Guild) -> None:
        await self.leave_if_not_allowed(guild)

    async def leave_if_not_allowed(self, guild: discord.Guild) -> None:
        """Project rule: the bot stays only in servers on the allow-list."""
        if guild.id in self.settings.guild_ids:
            return
        log.warning("Leaving server %s: it is not on the allow-list.", guild.id)
        try:
            await guild.leave()
        except discord.HTTPException:
            log.error("Could not leave server %s.", guild.id)


@app_commands.command(
    name="diagnose", description="Check a PC Doctor collector run and get the diagnosis."
)
@app_commands.describe(
    file="The .zip the PC Doctor collector made, or a PresentMon .csv",
    label="A short name for this run (optional)",
    public="Show the summary to the channel. The private link still goes only to you.",
)
@app_commands.guild_only()
async def diagnose(
    interaction: discord.Interaction,
    file: discord.Attachment,
    label: app_commands.Range[str, 0, core.MAX_LABEL_LENGTH] = "",
    public: bool = False,
) -> None:
    bot = interaction.client
    assert isinstance(bot, DoctorBot) and bot.http_client is not None
    settings = bot.settings

    async def refuse(text: str) -> None:
        await interaction.response.send_message(text, ephemeral=True, allowed_mentions=NO_MENTIONS)

    # The command is only registered in approved servers; this is the second lock.
    if interaction.guild_id not in settings.guild_ids:
        await refuse("This bot is not set up for this server.")
        return

    # Cheap checks first, before the cooldown is spent or anything is fetched.
    try:
        kind = core.check_attachment(file.filename, file.size, file.url, settings.max_upload_bytes)
    except core.AttachmentError as error:
        await refuse(core.format_error(error))
        return

    wait = bot.cooldown.retry_after(interaction.user.id)
    if wait > 0:
        await refuse(core.format_cooldown(wait))
        return

    # Private unless asked otherwise: the normal reply holds a private link.
    await interaction.response.defer(ephemeral=not public, thinking=True)
    try:
        async with bot.slots:
            data = await core.download_attachment(
                bot.http_client, file.url, settings.max_upload_bytes, kind
            )
            try:
                diagnosis = await core.diagnose(
                    bot.http_client, settings.api_url, data, kind, label, settings.api_token
                )
            finally:
                data.close()
    except core.UserError as error:
        await interaction.followup.send(core.format_error(error), allowed_mentions=NO_MENTIONS)
        return
    except Exception as error:
        # Only the error's type is logged: its text could hold a file name or a URL.
        log.error("Diagnose failed: %s", type(error).__name__)
        await interaction.followup.send(
            "Something went wrong while checking that file. Try again later.",
            allowed_mentions=NO_MENTIONS,
        )
        return

    reply = core.format_reply(diagnosis, settings.public_url, public=public, label=label)
    await interaction.followup.send(reply, allowed_mentions=NO_MENTIONS, suppress_embeds=True)
    if public and diagnosis.share_key:
        # The channel saw the summary; the link goes to the requester alone.
        await interaction.followup.send(
            core.format_link_note(settings.public_url, diagnosis.share_key),
            ephemeral=True,
            allowed_mentions=NO_MENTIONS,
            suppress_embeds=True,
        )
    log.info("Diagnose finished: verdict=%s", diagnosis.verdict or "unknown")


def main() -> None:
    core.configure_logging()
    try:
        settings = core.load_settings(os.environ)
    except core.ConfigError as error:
        sys.exit(f"pcdoctor-bot: {error}")
    bot = DoctorBot(settings)
    # log_handler=None: keep the logging set up above instead of discord.py's own.
    bot.run(settings.token, log_handler=None)


if __name__ == "__main__":
    main()
