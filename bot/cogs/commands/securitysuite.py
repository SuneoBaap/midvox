from __future__ import annotations

import asyncio
import textwrap
from collections import defaultdict
from io import BytesIO
from pathlib import Path

import aiosqlite
import discord
from discord.ext import commands
from PIL import Image, ImageDraw, ImageFont


DB_PATH = Path("db/security_suite.db")
ACCENT = 0xB7D56A


class SecuritySuite(commands.Cog):
    """Opt-in access control and forensic logging for each guild."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.invite_cache: dict[int, dict[str, int]] = defaultdict(dict)
        self._ready = asyncio.Event()
        self.bot.loop.create_task(self._initialize())
        self.bot.add_check(self._access_check)

    async def cog_unload(self):
        self.bot.remove_check(self._access_check)

    async def _initialize(self):
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """CREATE TABLE IF NOT EXISTS guild_settings (
                    guild_id INTEGER PRIMARY KEY,
                    access_enabled INTEGER NOT NULL DEFAULT 0,
                    visual_logs_enabled INTEGER NOT NULL DEFAULT 0,
                    invite_logs_enabled INTEGER NOT NULL DEFAULT 0,
                    log_channel_id INTEGER
                )"""
            )
            await db.execute(
                """CREATE TABLE IF NOT EXISTS access_entries (
                    guild_id INTEGER NOT NULL,
                    subject_type TEXT NOT NULL CHECK(subject_type IN ('user', 'role')),
                    subject_id INTEGER NOT NULL,
                    PRIMARY KEY (guild_id, subject_type, subject_id)
                )"""
            )
            await db.execute(
                """CREATE TABLE IF NOT EXISTS invite_joins (
                    guild_id INTEGER NOT NULL,
                    member_id INTEGER NOT NULL,
                    invite_code TEXT,
                    inviter_id INTEGER,
                    joined_at TEXT NOT NULL,
                    PRIMARY KEY (guild_id, member_id)
                )"""
            )
            await db.commit()
        self._ready.set()

    async def _settings(self, guild_id: int) -> tuple[bool, bool, bool, int | None]:
        await self._ready.wait()
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT access_enabled, visual_logs_enabled, invite_logs_enabled, log_channel_id "
                "FROM guild_settings WHERE guild_id = ?",
                (guild_id,),
            ) as cur:
                row = await cur.fetchone()
        return (bool(row[0]), bool(row[1]), bool(row[2]), row[3]) if row else (False, False, False, None)

    async def _set_setting(self, guild_id: int, field: str, value):
        allowed = {"access_enabled", "visual_logs_enabled", "invite_logs_enabled", "log_channel_id"}
        if field not in allowed:
            raise ValueError("unknown security setting")
        await self._ready.wait()
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("INSERT OR IGNORE INTO guild_settings (guild_id) VALUES (?)", (guild_id,))
            await db.execute(f"UPDATE guild_settings SET {field} = ? WHERE guild_id = ?", (value, guild_id))
            await db.commit()

    async def _access_check(self, ctx: commands.Context) -> bool:
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            return True
        command = ctx.command.qualified_name if ctx.command else ""
        if command.startswith("securitysuite"):
            return True
        enabled, _, _, _ = await self._settings(ctx.guild.id)
        if not enabled:
            return True
        if ctx.author == ctx.guild.owner or ctx.author.guild_permissions.administrator:
            return True
        if await self.bot.is_owner(ctx.author):
            return True
        role_ids = {role.id for role in ctx.author.roles}
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT subject_type, subject_id FROM access_entries WHERE guild_id = ?",
                (ctx.guild.id,),
            ) as cur:
                rows = await cur.fetchall()
        if any(kind == "user" and sid == ctx.author.id for kind, sid in rows):
            return True
        if any(kind == "role" and sid in role_ids for kind, sid in rows):
            return True
        raise commands.CheckFailure("This server only allows whitelisted users and roles to use MidVox commands.")

    async def _log_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        _, _, _, channel_id = await self._settings(guild.id)
        channel = guild.get_channel(channel_id) if channel_id else None
        return channel if isinstance(channel, discord.TextChannel) else None

    @staticmethod
    def _switch(value: str) -> bool:
        value = value.lower()
        if value in {"on", "enable", "enabled", "true"}:
            return True
        if value in {"off", "disable", "disabled", "false"}:
            return False
        raise commands.BadArgument("Use `on` or `off`.")

    @commands.group(name="securitysuite", aliases=["security"], invoke_without_command=True)
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def securitysuite(self, ctx: commands.Context):
        access, visual, invites, channel_id = await self._settings(ctx.guild.id)
        channel = ctx.guild.get_channel(channel_id) if channel_id else None
        embed = discord.Embed(title="MidVox Security Suite", color=ACCENT)
        embed.description = "New security modules remain off until an administrator enables them."
        embed.add_field(name="Command whitelist", value="On" if access else "Off", inline=True)
        embed.add_field(name="Visual message logs", value="On" if visual else "Off", inline=True)
        embed.add_field(name="Invite attribution", value="On" if invites else "Off", inline=True)
        embed.add_field(name="Advanced log channel", value=channel.mention if channel else "Not set", inline=False)
        embed.set_footer(text="Use securitysuite channel/logging/invites/access • Existing settings are unchanged")
        await ctx.reply(embed=embed, mention_author=False)

    @securitysuite.command(name="channel")
    @commands.has_permissions(administrator=True)
    async def suite_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        await self._set_setting(ctx.guild.id, "log_channel_id", channel.id)
        await ctx.reply(f"Advanced security logs will be sent to {channel.mention}.", mention_author=False)

    @securitysuite.command(name="logging")
    @commands.has_permissions(administrator=True)
    async def suite_logging(self, ctx: commands.Context, state: str):
        enabled = self._switch(state)
        if enabled and not (await self._settings(ctx.guild.id))[3]:
            return await ctx.reply("Set a channel first with `securitysuite channel #channel`.")
        await self._set_setting(ctx.guild.id, "visual_logs_enabled", int(enabled))
        await ctx.reply(f"Visual delete/edit logging is now **{'on' if enabled else 'off'}**.")

    @securitysuite.command(name="invites")
    @commands.has_permissions(administrator=True)
    async def suite_invites(self, ctx: commands.Context, state: str):
        enabled = self._switch(state)
        if enabled and not (await self._settings(ctx.guild.id))[3]:
            return await ctx.reply("Set a channel first with `securitysuite channel #channel`.")
        await self._set_setting(ctx.guild.id, "invite_logs_enabled", int(enabled))
        if enabled:
            await self._refresh_invites(ctx.guild)
        await ctx.reply(f"Exact invite attribution is now **{'on' if enabled else 'off'}**.")

    @securitysuite.command(name="access")
    @commands.has_permissions(administrator=True)
    async def suite_access(self, ctx: commands.Context, state: str):
        enabled = self._switch(state)
        await self._set_setting(ctx.guild.id, "access_enabled", int(enabled))
        await ctx.reply(f"Command whitelist enforcement is now **{'on' if enabled else 'off'}**.")

    async def _change_access(self, guild_id: int, kind: str, subject_id: int, add: bool):
        await self._ready.wait()
        async with aiosqlite.connect(DB_PATH) as db:
            if add:
                await db.execute(
                    "INSERT OR IGNORE INTO access_entries (guild_id, subject_type, subject_id) VALUES (?, ?, ?)",
                    (guild_id, kind, subject_id),
                )
            else:
                await db.execute(
                    "DELETE FROM access_entries WHERE guild_id = ? AND subject_type = ? AND subject_id = ?",
                    (guild_id, kind, subject_id),
                )
            await db.commit()

    @securitysuite.command(name="allowuser")
    @commands.has_permissions(administrator=True)
    async def allow_user(self, ctx: commands.Context, member: discord.Member):
        await self._change_access(ctx.guild.id, "user", member.id, True)
        await ctx.reply(f"Allowed {member.mention} to use bot commands.")

    @securitysuite.command(name="removeuser")
    @commands.has_permissions(administrator=True)
    async def remove_user(self, ctx: commands.Context, member: discord.Member):
        await self._change_access(ctx.guild.id, "user", member.id, False)
        await ctx.reply(f"Removed {member.mention} from the command whitelist.")

    @securitysuite.command(name="allowrole")
    @commands.has_permissions(administrator=True)
    async def allow_role(self, ctx: commands.Context, role: discord.Role):
        await self._change_access(ctx.guild.id, "role", role.id, True)
        await ctx.reply(f"Allowed {role.mention} to use bot commands.")

    @securitysuite.command(name="removerole")
    @commands.has_permissions(administrator=True)
    async def remove_role(self, ctx: commands.Context, role: discord.Role):
        await self._change_access(ctx.guild.id, "role", role.id, False)
        await ctx.reply(f"Removed {role.mention} from the command whitelist.")

    @securitysuite.command(name="whitelist")
    @commands.has_permissions(administrator=True)
    async def whitelist(self, ctx: commands.Context):
        await self._ready.wait()
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT subject_type, subject_id FROM access_entries WHERE guild_id = ? ORDER BY subject_type, subject_id",
                (ctx.guild.id,),
            ) as cur:
                rows = await cur.fetchall()
        users = [f"<@{sid}>" for kind, sid in rows if kind == "user"] or ["None"]
        roles = [f"<@&{sid}>" for kind, sid in rows if kind == "role"] or ["None"]
        embed = discord.Embed(title="Command Access Whitelist", color=ACCENT)
        embed.add_field(name="Users", value="\n".join(users)[:1024], inline=True)
        embed.add_field(name="Roles", value="\n".join(roles)[:1024], inline=True)
        await ctx.reply(embed=embed, mention_author=False)

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            if (await self._settings(guild.id))[2]:
                await self._refresh_invites(guild)

    async def _refresh_invites(self, guild: discord.Guild):
        try:
            invites = await guild.invites()
        except (discord.Forbidden, discord.HTTPException):
            return
        self.invite_cache[guild.id] = {invite.code: invite.uses or 0 for invite in invites}

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        if invite.guild:
            await self._refresh_invites(invite.guild)

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite):
        if invite.guild:
            self.invite_cache[invite.guild.id].pop(invite.code, None)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        _, _, enabled, _ = await self._settings(member.guild.id)
        if not enabled:
            return
        old = self.invite_cache.get(member.guild.id, {})
        used = None
        try:
            invites = await member.guild.invites()
            used = next((invite for invite in invites if (invite.uses or 0) > old.get(invite.code, 0)), None)
            self.invite_cache[member.guild.id] = {invite.code: invite.uses or 0 for invite in invites}
        except (discord.Forbidden, discord.HTTPException):
            invites = []
        inviter_id = used.inviter.id if used and used.inviter else None
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT OR REPLACE INTO invite_joins (guild_id, member_id, invite_code, inviter_id, joined_at) VALUES (?, ?, ?, ?, ?)",
                (member.guild.id, member.id, used.code if used else None, inviter_id, discord.utils.utcnow().isoformat()),
            )
            await db.commit()
        channel = await self._log_channel(member.guild)
        if not channel:
            return
        embed = discord.Embed(title="Member joined", color=ACCENT, timestamp=discord.utils.utcnow())
        embed.set_author(name=str(member), icon_url=member.display_avatar.url)
        embed.add_field(name="Member", value=f"{member.mention}\n`{member.id}`", inline=True)
        embed.add_field(name="Account created", value=discord.utils.format_dt(member.created_at, "R"), inline=True)
        if used:
            embed.add_field(name="Invite", value=f"`discord.gg/{used.code}`\nUses: **{used.uses or 0}**", inline=False)
            embed.add_field(name="Inviter", value=used.inviter.mention if used.inviter else "Unknown", inline=True)
        else:
            embed.add_field(name="Invite", value="Unknown, vanity URL, or missing Manage Server permission", inline=False)
        await channel.send(embed=embed)

    @staticmethod
    def _snapshot(title: str, author: str, channel: str, body: str) -> BytesIO:
        width = 1100
        wrapped = []
        for paragraph in (body or "No text content").splitlines() or [""]:
            wrapped.extend(textwrap.wrap(paragraph, width=88) or [""])
        wrapped = wrapped[:24]
        height = max(360, 220 + len(wrapped) * 30)
        image = Image.new("RGB", (width, height), "#10130e")
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default()
        draw.rounded_rectangle((24, 24, width - 24, height - 24), radius=24, fill="#1b2117", outline="#b7d56a", width=3)
        draw.text((60, 58), title, fill="#cde884", font=font)
        draw.text((60, 100), author, fill="#ffffff", font=font)
        draw.text((60, 130), channel, fill="#98a28f", font=font)
        draw.line((60, 170, width - 60, 170), fill="#394230", width=2)
        y = 200
        for line in wrapped:
            draw.text((60, y), line, fill="#e8ecdf", font=font)
            y += 30
        output = BytesIO()
        image.save(output, format="PNG", optimize=True)
        output.seek(0)
        return output

    async def _message_log(self, message: discord.Message, title: str, body: str):
        if not message.guild or message.author.bot:
            return
        _, enabled, _, _ = await self._settings(message.guild.id)
        if not enabled:
            return
        channel = await self._log_channel(message.guild)
        if not channel or channel.id == message.channel.id:
            return
        attachments = list(message.attachments)
        image_files = [a for a in attachments if (a.content_type or "").startswith("image/")]
        audio_files = [a for a in attachments if (a.content_type or "").startswith("audio/")]
        embed = discord.Embed(title=title, color=ACCENT, timestamp=discord.utils.utcnow())
        embed.set_author(name=str(message.author), icon_url=message.author.display_avatar.url)
        embed.add_field(name="Channel", value=message.channel.mention, inline=True)
        embed.add_field(name="Author ID", value=f"`{message.author.id}`", inline=True)
        if attachments:
            lines = [f"[{a.filename}]({a.url}) • {a.size / 1024:.1f} KB • {a.content_type or 'unknown'}" for a in attachments]
            embed.add_field(name=f"Attachments ({len(attachments)})", value="\n".join(lines)[:1024], inline=False)
        if image_files:
            embed.set_image(url=image_files[0].url)
        if audio_files:
            embed.add_field(name="Audio evidence", value="Original audio links are preserved above.", inline=False)
        snapshot = self._snapshot(title, str(message.author), f"#{message.channel}", body)
        await channel.send(embed=embed, file=discord.File(snapshot, filename="message-evidence.png"))

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        attachment_text = "\n".join(f"Attachment: {a.filename} ({a.url})" for a in message.attachments)
        body = "\n".join(part for part in (message.content, attachment_text) if part)
        await self._message_log(message, "Message deleted", body)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if before.content == after.content:
            return
        body = f"BEFORE\n{before.content or 'No text'}\n\nAFTER\n{after.content or 'No text'}"
        await self._message_log(before, "Message edited", body)


async def setup(bot):
    await bot.add_cog(SecuritySuite(bot))
