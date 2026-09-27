import discord
from discord.ext import commands
from discord.ui import LayoutView, TextDisplay, Separator, Container, Button, ActionRow
import aiosqlite
import os
import time

from utils.Tools import blacklist_check, ignore_check
from utils.cv2 import CV2, build_container, card_text_items
from utils.emoji import TICK, MENTION, SEED, TIME
from utils.config import *

DB_PATH = "db/afk.db"
THEME_COLOR = 0x8A9A5B
FOOTER_TEXT = f"Developed by {BRAND_NAME}"

class AfkTypeView(LayoutView):
    def __init__(self, author, reason, timeout=60):
        super().__init__(timeout=timeout)
        self.author = author
        self.reason = reason
        self.value = None

        self.global_btn = Button(label="Global AFK", style=discord.ButtonStyle.primary)
        self.local_btn = Button(label="Local AFK", style=discord.ButtonStyle.success)

        self.global_btn.callback = self.global_afk
        self.local_btn.callback = self.local_afk

        self.add_item(
            build_container(
                *card_text_items("Choose your AFK type", (
                    f"Reason: **{reason}**\nSelect Global AFK or Local AFK below.",
                )),
                ActionRow(self.global_btn, self.local_btn)
            )
        )

    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(
                f"Only **{self.author.display_name}** can use this button.", ephemeral=True)
            return False
        return True

    async def global_afk(self, interaction: discord.Interaction):
        self.value = "global"
        await interaction.response.defer()
        self.stop()

    async def local_afk(self, interaction: discord.Interaction):
        self.value = "local"
        await interaction.response.defer()
        self.stop()

class AfkSuccess(LayoutView):
    def __init__(self, type_val, reason):
        super().__init__(timeout=None)
        self.add_item(
            build_container(*card_text_items(f"{TICK} AFK Activated", (
                f"You are now marked as **{type_val.capitalize()} AFK**.\n{SEED} **Reason:** {reason}",
            )))
        )

class AfkMention(LayoutView):
    def __init__(self, user_mention, afk_time, reason):
        super().__init__(timeout=None)
        self.add_item(
            build_container(*card_text_items(f"{user_mention.display_name} is AFK", (
                f"Went AFK <t:{int(afk_time)}:R>.\n**Reason:** {reason}",
            )))
        )

class AfkWelcomeBack(LayoutView):
    def __init__(self, author, mentions, elapsed_time):
        super().__init__(timeout=None)
        self.add_item(
            build_container(*card_text_items(f"{author.display_name} is back", (
                f"{TICK} **AFK Removed**\n{MENTION} **Mentions:** {mentions}\n{TIME} **AFK time:** {elapsed_time}",
            )))
        )

class afk(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.theme_color = THEME_COLOR
        self.bot.loop.create_task(self.initialize_db())

    async def initialize_db(self):
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS afk (
                    user_id INTEGER PRIMARY KEY,
                    type TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    time INTEGER NOT NULL,
                    mentions INTEGER NOT NULL DEFAULT 0
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS afk_guild (
                    user_id INTEGER NOT NULL,
                    guild_id INTEGER NOT NULL,
                    PRIMARY KEY (user_id, guild_id)
                )
            """)
            await db.commit()

    async def time_formatter(self, seconds: float):
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        d, h = divmod(h, 24)
        parts = []
        if d > 0: parts.append(f"{d}d")
        if h > 0: parts.append(f"{h}h")
        if m > 0: parts.append(f"{m}m")
        if s > 0: parts.append(f"{s}s")
        return " ".join(parts) or "0s"

    async def set_afk(self, user, afk_type, reason, current_guild=None):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM afk_guild WHERE user_id = ?", (user.id,))

            await db.execute(
                "INSERT OR REPLACE INTO afk (user_id, type, reason, time, mentions) VALUES (?, ?, ?, ?, 0)",
                (user.id, afk_type, reason, int(time.time()))
            )
            if afk_type == "global":
                for g in self.bot.guilds:
                    if g.get_member(user.id):
                        await db.execute("INSERT OR IGNORE INTO afk_guild (user_id, guild_id) VALUES (?, ?)", (user.id, g.id))
            elif current_guild:
                await db.execute("INSERT OR IGNORE INTO afk_guild (user_id, guild_id) VALUES (?, ?)", (user.id, current_guild.id))

            await db.commit()

    async def clear_afk(self, message):
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("SELECT 1 FROM afk_guild WHERE user_id = ? AND guild_id = ?", (message.author.id, message.guild.id))
            if not await cursor.fetchone():
                return

            cursor = await db.execute("SELECT type, time, mentions FROM afk WHERE user_id = ?", (message.author.id,))
            afk_data = await cursor.fetchone()
            if not afk_data: return

            afk_type, afk_time, mentions = afk_data
            elapsed_time = await self.time_formatter(time.time() - afk_time)

            if afk_type == 'global':
                await db.execute("DELETE FROM afk WHERE user_id = ?", (message.author.id,))
                await db.execute("DELETE FROM afk_guild WHERE user_id = ?", (message.author.id,))
            else:
                await db.execute("DELETE FROM afk_guild WHERE user_id = ? AND guild_id = ?", (message.author.id, message.guild.id))
                cursor_check = await db.execute("SELECT 1 FROM afk_guild WHERE user_id = ?", (message.author.id,))
                if not await cursor_check.fetchone():
                    await db.execute("DELETE FROM afk WHERE user_id = ?", (message.author.id,))

            await db.commit()

            view = AfkWelcomeBack(message.author, mentions, elapsed_time)
            try:
                await message.reply(view=view, delete_after=10, mention_author=False)
            except discord.HTTPException:
                pass

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return

        await self.clear_afk(message)

        if not message.mentions:
            return

        async with aiosqlite.connect(DB_PATH) as db:
            for mentioned in message.mentions:
                if mentioned.bot or mentioned.id == message.author.id:
                    continue

                cursor = await db.execute("SELECT 1 FROM afk_guild WHERE user_id = ? AND guild_id = ?", (mentioned.id, message.guild.id))
                if await cursor.fetchone():
                    cursor_main = await db.execute("SELECT reason, mentions, time FROM afk WHERE user_id = ?", (mentioned.id,))
                    afk_data = await cursor_main.fetchone()
                    if not afk_data: continue

                    reason, mentions, afk_time = afk_data

                    view = AfkMention(mentioned, afk_time, reason)
                    await message.reply(view=view, delete_after=10, mention_author=False)

                    new_mentions = mentions + 1
                    await db.execute("UPDATE afk SET mentions = ? WHERE user_id = ?", (new_mentions, mentioned.id))
                    await db.commit()

                    dm_embed = discord.Embed(description=f"You were mentioned in **{message.guild.name}** by **{message.author}**", color=self.theme_color)
                    dm_embed.add_field(name="Total Mentions", value=str(new_mentions))
                    dm_embed.add_field(name="Jump to Message", value=f"[Click Here]({message.jump_url})")
                    dm_embed.set_footer(text=FOOTER_TEXT, icon_url=self.bot.user.avatar.url)
                    try:
                        await mentioned.send(embed=dm_embed)
                    except discord.Forbidden:
                        pass

    @commands.hybrid_command(name="afk", description="Set your AFK status with a reason (Global or Local).")
    @blacklist_check()
    @ignore_check()
    @commands.guild_only()
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def afk(self, ctx: commands.Context, *, reason: str = "I am AFK"):
        if any(w in reason.lower() for w in ("discord.gg", "gg/")):
            return await ctx.send(view=CV2("AFK reason blocked", "Advertising is not allowed in AFK reasons."), ephemeral=True)

        type_view = AfkTypeView(ctx.author, reason)
        msg = await ctx.reply(view=type_view, mention_author=False)
        await type_view.wait()

        if not type_view.value:
            await msg.edit(content=None, view=CV2("AFK setup timed out", "Run the AFK command again when you are ready."))
            return

        await self.set_afk(ctx.author, type_view.value, reason, ctx.guild)

        success_view = AfkSuccess(type_view.value, reason)
        await msg.edit(view=success_view)

async def setup(bot):
    await bot.add_cog(afk(bot))
