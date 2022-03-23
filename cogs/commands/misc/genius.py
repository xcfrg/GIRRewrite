import datetime
import re

import discord
from discord import app_commands
from data.services import guild_service
from discord.ext import commands
from utils import BlooContext, cfg
from utils.context import transform_context
from utils.framework import genius_or_submod_and_up, whisper_in_general
from utils.views import CommonIssueModal, EditCommonIssue, issue_autocomplete, GenericDescriptionModal

# from utils.views.prompt import GenericDescriptionModal


async def prepare_issue_response(title, description, author, buttons=[], image: discord.Attachment = None):
    embed = discord.Embed(title=title)
    embed.color = discord.Color.random()
    embed.description = description
    f = None

    # did the user want to attach an image to this tag?
    if image is not None:
        f = await image.to_file()
        embed.set_image(url=f"attachment://{f.filename}")

    embed.set_footer(text=f"Submitted by {author}")
    embed.timestamp = datetime.datetime.now()

    if not buttons or buttons is None:
        return embed, f, None

    view = discord.ui.View()
    for label, link in buttons:
        # regex match emoji in label
        custom_emojis = re.search(
            r'<:\d+>|<:.+?:\d+>|<a:.+:\d+>|[\U00010000-\U0010ffff]', label)
        if custom_emojis is not None:
            emoji = custom_emojis.group(0).strip()
            label = label.replace(emoji, '')
            label = label.strip()
        else:
            emoji = None
        view.add_item(discord.ui.Button(
            style=discord.ButtonStyle.link, label=label, url=link, emoji=emoji))

    return embed, f, view


class Genius(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.cache = []

    # commonissue = discord.SlashCommandGroup("commonissue", "Interact with common issues", guild_ids=[
    #     cfg.guild_id], permissions=slash_perms.genius_or_submod_and_up())
    common_issue = app_commands.Group(name="commonissue", description="Interact with tags", guild_ids=[cfg.guild_id])

    # TODO: image only transformer
    @genius_or_submod_and_up()
    @common_issue.command(description="Submit a new common issue")
    @app_commands.describe(title="Title of the issue")
    @app_commands.describe(image="Image to show in issue")
    @transform_context
    async def new(self, ctx: BlooContext, *, title: str,  image: discord.Attachment = None) -> None:
        # get #common-issues channel
        channel = ctx.guild.get_channel(
            guild_service.get_guild().channel_common_issues)
        if not channel:
            raise commands.BadArgument("common issues channel not found")

        # ensure the attached file is an image
        if image is not None:
            _type = image.content_type
            if _type not in ["image/png", "image/jpeg", "image/gif", "image/webp"]:
                raise commands.BadArgument("Attached file was not an image.")

        # prompt the user for common issue body
        modal = CommonIssueModal(ctx=ctx, author=ctx.author, title=title)
        await ctx.interaction.response.send_modal(modal)
        await modal.wait()

        description = modal.description
        buttons = modal.buttons

        if not description:
            if not modal.callback_triggered:
                await ctx.send_warning("Cancelled adding common issue.")
            return

        embed, f, view = await prepare_issue_response(title, description, ctx.author, buttons, image)

        await channel.send(embed=embed, file=f, view=view)
        await ctx.send_success("Common issue posted!", delete_after=5, followup=True)
        await self.do_reindex(channel)

    @genius_or_submod_and_up()
    @common_issue.command(description="Submit a new common issue")
    @app_commands.describe(title="Title of the issue")
    @app_commands.autocomplete(title=issue_autocomplete)
    @app_commands.describe(image="Image to show in issue")
    @transform_context
    async def edit(self, ctx: BlooContext, *, title: str, image: discord.Attachment = None) -> None:
        channel = ctx.guild.get_channel(
            guild_service.get_guild().channel_common_issues)
        if not channel:
            raise commands.BadArgument("common issues channel not found")

        if title not in self.bot.issue_cache.cache:
            raise commands.BadArgument(
                "Issue not found! Title must match one of the embeds exactly, use autocomplete to help!")

        message: discord.Message = self.bot.issue_cache.cache[title]

        # ensure the attached file is an image
        if image is not None:
            _type = image.content_type
            if _type not in ["image/png", "image/jpeg", "image/gif", "image/webp"]:
                raise commands.BadArgument("Attached file was not an image.")

        # prompt the user for common issue body
        modal = EditCommonIssue(
            author=ctx.author, ctx=ctx, title=title, issue_message=message)
        await ctx.interaction.response.send_modal(modal)
        await modal.wait()

        if not modal.edited:
            if not modal.callback_triggered:
                await ctx.send_warning("Cancelled adding common issue.")
            return

        description = modal.description
        buttons = modal.buttons

        embed, f, view = await prepare_issue_response(title, description, ctx.author, buttons, image)
        embed.set_footer(text=message.embeds[0].footer.text)
        await message.edit(embed=embed, attachments=[f] if f is not None else discord.utils.MISSING, view=view)
        await ctx.send_success("Common issue edited!", delete_after=5, followup=True)
        await self.do_reindex(channel)

    @genius_or_submod_and_up()
    @app_commands.guilds(cfg.guild_id)
    @app_commands.command(description="Post an embed")
    @app_commands.describe(title="Title of the embed")
    @app_commands.describe(channel="Channel to post the embed in")
    @app_commands.describe(image="Image to show in embed")
    @transform_context
    async def postembed(self, ctx: BlooContext, *, title: str, channel: discord.TextChannel = None, image: discord.Attachment = None):
        post_channel = channel or ctx.channel

        # ensure the attached file is an image
        if image is not None:
            _type = image.content_type
            if _type not in ["image/png", "image/jpeg", "image/gif", "image/webp"]:
                raise commands.BadArgument("Attached file was not an image.")

        # prompt the user for common issue body
        modal = GenericDescriptionModal(ctx=ctx,
            author=ctx.author, title=f"New embed — {title}")
        await ctx.interaction.response.send_modal(modal)
        await modal.wait()

        description = modal.value
        if not description:
            await ctx.send_warning("Cancelled new embed.")
            return

        embed, f, _ = await prepare_issue_response(title, description, ctx.author, image)
        await post_channel.send(embed=embed, file=f)

        if post_channel != ctx.channel:
            await ctx.send_success(f"Embed posted in {post_channel.mention}!", delete_after=5)

    @genius_or_submod_and_up()
    @common_issue.command(description="Repost common-issues table of contents")
    @transform_context
    async def reindex(self, ctx: BlooContext):
        # get #common-issues channel
        channel: discord.TextChannel = ctx.guild.get_channel(
            guild_service.get_guild().channel_common_issues)
        if not channel:
            raise commands.BadArgument("common issues channel not found")

        await ctx.defer(ephemeral=True)
        res = await self.do_reindex(channel)

        if res is None:
            raise commands.BadArgument("Something unexpected occured")

        count, page = res
        await ctx.send_success(f"Indexed {count} issues and posted {page} Table of Contents embeds!")

    async def do_reindex(self, channel):
        contents = {}
        async for message in channel.history(limit=None, oldest_first=True):
            if message.author.id != self.bot.user.id:
                continue

            if not message.embeds:
                continue

            embed = message.embeds[0]
            if not embed.footer.text:
                continue

            if embed.footer.text.startswith("Submitted by"):
                contents[f"{embed.title}"] = message
            elif embed.footer.text.startswith("Table of Contents"):
                await message.delete()
            else:
                continue

        page = 1
        count = 1
        toc_embed = discord.Embed(
            title="Table of Contents", description="Click on a link to jump to the issue!\n", color=discord.Color.gold())
        toc_embed.set_footer(text=f"Table of Contents • Page {page}")
        for title, message in contents.items():
            this_line = f"\n{count}. [{title}]({message.jump_url})"
            count += 1
            if len(toc_embed.description) + len(this_line) < 4096:
                toc_embed.description += this_line
            else:
                await channel.send(embed=toc_embed)
                page += 1
                toc_embed.description = ""
                toc_embed.title = ""
                toc_embed.set_footer(text=f"Table of Contents • Page {page}")

        self.bot.issue_cache.cache = contents
        await channel.send(embed=toc_embed)
        return count, page

    @genius_or_submod_and_up()
    @app_commands.guilds(cfg.guild_id)
    @app_commands.command(description="Post raw body of an embed")
    @app_commands.describe(channel="Channel to post the embed is in")
    @app_commands.describe(message_id="ID of the message with the embed")
    @app_commands.describe(mobile_friendly="Whether to display the response in a mobile friendly format")
    @transform_context
    async def rawembed(self, ctx: BlooContext, *, channel: discord.TextChannel, message_id: str, mobile_friendly: bool):
        try:
            message_id = int(message_id)
        except:
            raise commands.BadArgument("Invalid message ID!")

        try:
            message: discord.Message = await channel.fetch_message(message_id)
        except Exception:
            raise commands.BadArgument(
                "Could not find a message with that ID!")

        if message.author != ctx.me:
            raise commands.BadArgument("I didn't post that embed!")

        if len(message.embeds) == 0:
            raise commands.BadArgument("Message does not have an embed!")

        _file = message.embeds[0].image
        response = discord.utils.escape_markdown(
            message.embeds[0].description) if not mobile_friendly else message.embeds[0].description
        parts = [response[i:i+2000] for i in range(0, len(response), 2000)]

        for i, part in enumerate(parts):
            if i == 0:
                await ctx.respond(part, allowed_mentions=discord.AllowedMentions(users=False, roles=False, everyone=False))
            else:
                await ctx.send(part, allowed_mentions=discord.AllowedMentions(users=False, roles=False, everyone=False))

        if _file:
            await ctx.send(_file.url, allowed_mentions=discord.AllowedMentions(users=False, roles=False, everyone=False))

    @app_commands.guilds(cfg.guild_id)
    @app_commands.command(description="Post the embed for one of the common issues")
    @app_commands.describe(title="Issue title")
    @app_commands.autocomplete(title=issue_autocomplete)
    @app_commands.describe(user_to_mention="User to mention in the response")
    @transform_context
    @whisper_in_general
    async def issue(self, ctx: BlooContext, title: str, user_to_mention: discord.Member = None):
        if title not in self.bot.issue_cache:
            raise commands.BadArgument(
                "Issue not found! Title must match one of the embeds exactly, use autocomplete to help!")

        message: discord.Message = self.bot.issue_cache.cache[title]
        embed = message.embeds[0]
        view = discord.ui.View()
        components = message.components
        if components:
            for component in components:
                if isinstance(component, discord.ActionRow):
                    for child in component.children:
                        b = discord.ui.Button(
                            style=child.style, emoji=child.emoji, label=child.label, url=child.url)
                        view.add_item(b)

        if user_to_mention is not None:
            title = f"Hey {user_to_mention.mention}, have a look at this!"
        else:
            title = None

        await ctx.respond_or_edit(content=title, embed=embed, ephemeral=ctx.whisper, view=view)


async def setup(bot):
    await bot.add_cog(Genius(bot))