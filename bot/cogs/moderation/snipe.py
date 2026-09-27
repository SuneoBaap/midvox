import discord
from collections import defaultdict, deque
from utils.emoji import ERROR
from discord.ext import commands
from datetime import datetime

class Snipe(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Keep the latest 25 deleted messages in every channel.
        self.sniped_messages = defaultdict(lambda: deque(maxlen=25))

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        # Ignore messages from bots or from DMs
        if message.author.bot or not message.guild:
            return

        # Store the message details
        self.sniped_messages[message.channel.id].appendleft({
            'content': message.content,
            'author': message.author,
            'deleted_at': datetime.utcnow(),
            'attachments': [(a.filename, a.url, a.content_type, a.size) for a in message.attachments]
        })

    @commands.command(name='snipe', help="Shows the most recently deleted message in the channel.")
    @commands.has_permissions(manage_messages=True)
    async def snipe(self, ctx, index: int = 1):
        # Check if there is a sniped message for the current channel
        history = self.sniped_messages.get(ctx.channel.id)
        if history and 1 <= index <= len(history):
            sniped_data = history[index - 1]
            author = sniped_data['author']
            content = sniped_data['content']
            deleted_at = sniped_data['deleted_at']

            # If the deleted message had no text content (e.g., only an image)
            if not content:
                content = "No text content was found in the deleted message."

            # Create the simple embed
            embed = discord.Embed(
                description=content,
                color=0x8A9A5B,
                timestamp=deleted_at
            )
            embed.set_author(name=f"Sniped message from {author.name}", icon_url=author.display_avatar.url)
            attachments = sniped_data.get('attachments', [])
            if attachments:
                links = [f"[{name}]({url}) • {size / 1024:.1f} KB" for name, url, _, size in attachments]
                embed.add_field(name=f"Attachments ({len(attachments)})", value="\n".join(links)[:1024], inline=False)
                first_image = next((url for _, url, kind, _ in attachments if (kind or '').startswith('image/')), None)
                if first_image:
                    embed.set_image(url=first_image)
            embed.set_footer(text=f"Snipe {index}/{len(history)} • Deleted at")

            await ctx.send(embed=embed)
        else:
            # Send an error message if no message is stored for this channel
            embed = discord.Embed(
                description=f"{ERROR} | No deleted message exists at index `{index}`. This channel currently has {len(history or [])}/25 stored.",
                color=0x8A9A5B
            )
            await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Snipe(bot))
