import os
import sqlite3
import asyncio
from datetime import datetime, timezone, timedelta

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

# ================== CONFIG ==================

load_dotenv()
TOKEN = os.getenv("TOKEN")

# IDs
GUILD_ID = 1472748211038064832
STAFF_ROLE_ID = 1472955865144365148
LOG_CHANNEL_ID = 1473410235040399392

COMMUNITY_ID = 299952594
VOICE_CHANNEL_ID = 1483878606974226432

DB_PATH = "moderation.db"

# ================== BOT SETUP ==================

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True
intents.presences = False

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree


# ================== DATABASE ==================

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS warnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            moderator_id INTEGER NOT NULL,
            reason TEXT NOT NULL,
            timestamp TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def add_warning(user_id: int, moderator_id: int, reason: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO warnings (user_id, moderator_id, reason, timestamp) VALUES (?, ?, ?, ?)",
        (user_id, moderator_id, reason, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()


def get_warnings(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT id, moderator_id, reason, timestamp FROM warnings WHERE user_id = ? ORDER BY id ASC",
        (user_id,),
    )
    rows = c.fetchall()
    conn.close()
    return rows


def remove_warning(warn_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM warnings WHERE id = ?", (warn_id,))
    changes = c.rowcount
    conn.commit()
    conn.close()
    return changes > 0


# ================== UTILITIES ==================

def is_staff(interaction: discord.Interaction) -> bool:
    if interaction.user.guild_permissions.administrator:
        return True
    role = interaction.guild.get_role(STAFF_ROLE_ID)
    if role is None:
        return False
    return role in getattr(interaction.user, "roles", [])


def staff_only():
    async def predicate(interaction: discord.Interaction):
        if not is_staff(interaction):
            await interaction.response.send_message(
                "You do not have permission to use this command.", ephemeral=True
            )
            return False
        return True

    return app_commands.check(predicate)


async def get_log_channel(guild: discord.Guild) -> discord.TextChannel | None:
    channel = guild.get_channel(LOG_CHANNEL_ID)
    if isinstance(channel, discord.TextChannel):
        return channel
    return None


def format_dt(dt_str: str) -> str:
    try:
        dt = datetime.fromisoformat(dt_str)
        return f"<t:{int(dt.timestamp())}:R>"
    except Exception:
        return dt_str


# ================== ROBLOX MEMBER COUNTER ==================

async def fetch_community_member_count():
    url = f"https://groups.roblox.com/v1/communities/{COMMUNITY_ID}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as r:
            if r.status != 200:
                print(f"[COUNTER] Failed to fetch community data: HTTP {r.status}")
                return None
            data = await r.json()
            return data.get("memberCount")


async def update_member_count_task():
    await bot.wait_until_ready()
    print("[COUNTER] Member count task started.")

    while not bot.is_closed():
        try:
            count = await fetch_community_member_count()
            if count is not None:
                guild = bot.get_guild(GUILD_ID)
                if guild:
                    channel = guild.get_channel(VOICE_CHANNEL_ID)
                    if isinstance(channel, discord.VoiceChannel):
                        try:
                            await channel.edit(name=f"Members: {count}")
                            print(f"[COUNTER] Updated member count to {count}")
                        except Exception as e:
                            print(f"[COUNTER] Failed to update channel name: {e}")
                    else:
                        print("[COUNTER] Voice channel not found or wrong type.")
                else:
                    print("[COUNTER] Guild not found.")
            else:
                print("[COUNTER] Could not fetch member count.")
        except Exception as e:
            print(f"[COUNTER] Error in member count loop: {e}")

        await asyncio.sleep(300)  # 5 minutes


# ================== LOGGING HELPERS ==================

async def send_log_embed(guild: discord.Guild, embed: discord.Embed):
    channel = await get_log_channel(guild)
    if channel is None:
        return
    try:
        await channel.send(embed=embed)
    except Exception as e:
        print(f"[LOG] Failed to send log embed: {e}")


# ================== EVENTS: LOGGING ==================

@bot.event
async def on_message_delete(message: discord.Message):
    if message.guild is None or message.author.bot:
        return

    embed = discord.Embed(
        title="Message Deleted",
        color=discord.Color.red(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="Author", value=f"{message.author} ({message.author.id})", inline=False)
    embed.add_field(name="Channel", value=f"{message.channel.mention}", inline=False)
    content = message.content or "*No content*"
    if len(content) > 1024:
        content = content[:1021] + "..."
    embed.add_field(name="Content", value=content, inline=False)
    await send_log_embed(message.guild, embed)


@bot.event
async def on_message_edit(before: discord.Message, after: discord.Message):
    if before.guild is None or before.author.bot:
        return
    if before.content == after.content:
        return

    embed = discord.Embed(
        title="Message Edited",
        color=discord.Color.orange(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="Author", value=f"{before.author} ({before.author.id})", inline=False)
    embed.add_field(name="Channel", value=before.channel.mention, inline=False)

    before_content = before.content or "*No content*"
    after_content = after.content or "*No content*"
    if len(before_content) > 1024:
        before_content = before_content[:1021] + "..."
    if len(after_content) > 1024:
        after_content = after_content[:1021] + "..."

    embed.add_field(name="Before", value=before_content, inline=False)
    embed.add_field(name="After", value=after_content, inline=False)
    await send_log_embed(before.guild, embed)


@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    if before.guild is None:
        return

    # Nickname change
    if before.nick != after.nick:
        embed = discord.Embed(
            title="Nickname Changed",
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="User", value=f"{before} ({before.id})", inline=False)
        embed.add_field(name="Before", value=before.nick or before.name, inline=True)
        embed.add_field(name="After", value=after.nick or after.name, inline=True)
        await send_log_embed(before.guild, embed)

    # Roles change
    before_roles = set(before.roles)
    after_roles = set(after.roles)

    added = after_roles - before_roles
    removed = before_roles - after_roles

    if added:
        for role in added:
            if role.is_default():
                continue
            embed = discord.Embed(
                title="Role Added",
                color=discord.Color.green(),
                timestamp=datetime.now(timezone.utc),
            )
            embed.add_field(name="User", value=f"{after} ({after.id})", inline=False)
            embed.add_field(name="Role", value=f"{role.mention} ({role.id})", inline=False)
            await send_log_embed(after.guild, embed)

    if removed:
        for role in removed:
            if role.is_default():
                continue
            embed = discord.Embed(
                title="Role Removed",
                color=discord.Color.red(),
                timestamp=datetime.now(timezone.utc),
            )
            embed.add_field(name="User", value=f"{after} ({after.id})", inline=False)
            embed.add_field(name="Role", value=f"{role.name} ({role.id})", inline=False)
            await send_log_embed(after.guild, embed)


@bot.event
async def on_member_join(member: discord.Member):
    if member.guild is None:
        return
    embed = discord.Embed(
        title="Member Joined",
        color=discord.Color.green(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="User", value=f"{member} ({member.id})", inline=False)
    await send_log_embed(member.guild, embed)


@bot.event
async def on_member_remove(member: discord.Member):
    if member.guild is None:
        return
    embed = discord.Embed(
        title="Member Left",
        color=discord.Color.red(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="User", value=f"{member} ({member.id})", inline=False)
    await send_log_embed(member.guild, embed)


@bot.event
async def on_guild_role_create(role: discord.Role):
    embed = discord.Embed(
        title="Role Created",
        color=discord.Color.green(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="Role", value=f"{role.name} ({role.id})", inline=False)
    await send_log_embed(role.guild, embed)


@bot.event
async def on_guild_role_delete(role: discord.Role):
    embed = discord.Embed(
        title="Role Deleted",
        color=discord.Color.red(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="Role", value=f"{role.name} ({role.id})", inline=False)
    await send_log_embed(role.guild, embed)


@bot.event
async def on_guild_channel_create(channel: discord.abc.GuildChannel):
    embed = discord.Embed(
        title="Channel Created",
        color=discord.Color.green(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="Channel", value=f"{channel.name} ({channel.id})", inline=False)
    await send_log_embed(channel.guild, embed)


@bot.event
async def on_guild_channel_delete(channel: discord.abc.GuildChannel):
    embed = discord.Embed(
        title="Channel Deleted",
        color=discord.Color.red(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="Channel", value=f"{channel.name} ({channel.id})", inline=False)
    await send_log_embed(channel.guild, embed)


@bot.event
async def on_guild_channel_update(before: discord.abc.GuildChannel, after: discord.abc.GuildChannel):
    if before.name != after.name:
        embed = discord.Embed(
            title="Channel Renamed",
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Before", value=f"{before.name}", inline=True)
        embed.add_field(name="After", value=f"{after.name}", inline=True)
        embed.add_field(name="Channel ID", value=str(after.id), inline=False)
        await send_log_embed(after.guild, embed)


# ================== SLASH COMMANDS ==================

# ---- Public: userinfo, serverinfo ----

@tree.command(name="userinfo", description="Show information about a user.")
@app_commands.describe(user="The user to get info about")
async def userinfo(interaction: discord.Interaction, user: discord.User | None = None):
    user = user or interaction.user
    member = interaction.guild.get_member(user.id) if interaction.guild else None

    embed = discord.Embed(
        title=f"User Info - {user}",
        color=discord.Color.blurple(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.add_field(name="ID", value=str(user.id), inline=False)
    embed.add_field(name="Created", value=f"<t:{int(user.created_at.timestamp())}:R>", inline=False)

    if member:
        embed.add_field(name="Joined", value=f"<t:{int(member.joined_at.timestamp())}:R>", inline=False)
        roles = [r.mention for r in member.roles if not r.is_default()]
        embed.add_field(name="Roles", value=", ".join(roles) if roles else "None", inline=False)

    await interaction.response.send_message(embed=embed)


@tree.command(name="serverinfo", description="Show information about the server.")
async def serverinfo(interaction: discord.Interaction):
    guild = interaction.guild
    if guild is None:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return

    embed = discord.Embed(
        title=f"Server Info - {guild.name}",
        color=discord.Color.blurple(),
        timestamp=datetime.now(timezone.utc),
    )
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)

    embed.add_field(name="ID", value=str(guild.id), inline=False)
    embed.add_field(name="Owner", value=f"{guild.owner} ({guild.owner_id})", inline=False)
    embed.add_field(name="Members", value=str(guild.member_count), inline=False)
    embed.add_field(name="Created", value=f"<t:{int(guild.created_at.timestamp())}:R>", inline=False)
    embed.add_field(name="Channels", value=str(len(guild.channels)), inline=False)
    embed.add_field(name="Roles", value=str(len(guild.roles)), inline=False)

    await interaction.response.send_message(embed=embed)


# ---- Moderation: staff-only ----

@tree.command(name="warn", description="Warn a user.")
@staff_only()
@app_commands.describe(user="User to warn", reason="Reason for the warning")
async def warn(interaction: discord.Interaction, user: discord.Member, reason: str):
    add_warning(user.id, interaction.user.id, reason)
    embed = discord.Embed(
        title="User Warned",
        color=discord.Color.orange(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="User", value=f"{user} ({user.id})", inline=False)
    embed.add_field(name="Moderator", value=f"{interaction.user} ({interaction.user.id})", inline=False)
    embed.add_field(name="Reason", value=reason, inline=False)

    await interaction.response.send_message(embed=embed)
    if interaction.guild:
        await send_log_embed(interaction.guild, embed)


@tree.command(name="warnings", description="View a user's warnings.")
@staff_only()
@app_commands.describe(user="User to view warnings for")
async def warnings(interaction: discord.Interaction, user: discord.Member):
    warns = get_warnings(user.id)
    embed = discord.Embed(
        title=f"Warnings for {user}",
        color=discord.Color.orange(),
        timestamp=datetime.now(timezone.utc),
    )

    if not warns:
        embed.description = "No warnings found."
    else:
        for wid, mod_id, reason, ts in warns:
            embed.add_field(
                name=f"ID: {wid} • Moderator: {mod_id}",
                value=f"Reason: {reason}\nTime: {format_dt(ts)}",
                inline=False,
            )

    await interaction.response.send_message(embed=embed, ephemeral=True)


@tree.command(name="warnremove", description="Remove a warning by ID.")
@staff_only()
@app_commands.describe(warning_id="The ID of the warning to remove")
async def warnremove(interaction: discord.Interaction, warning_id: int):
    success = remove_warning(warning_id)
    if success:
        msg = f"Warning with ID `{warning_id}` has been removed."
        color = discord.Color.green()
    else:
        msg = f"No warning found with ID `{warning_id}`."
        color = discord.Color.red()

    embed = discord.Embed(
        title="Warn Remove",
        description=msg,
        color=color,
        timestamp=datetime.now(timezone.utc),
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@tree.command(name="ban", description="Ban a user from the server.")
@staff_only()
@app_commands.describe(user="User to ban", reason="Reason for the ban")
async def ban(interaction: discord.Interaction, user: discord.Member, reason: str):
    await interaction.response.defer(ephemeral=True)
    try:
        await user.ban(reason=f"{interaction.user} - {reason}")
        embed = discord.Embed(
            title="User Banned",
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="User", value=f"{user} ({user.id})", inline=False)
        embed.add_field(name="Moderator", value=f"{interaction.user} ({interaction.user.id})", inline=False)
        embed.add_field(name="Reason", value=reason, inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)
        if interaction.guild:
            await send_log_embed(interaction.guild, embed)
    except Exception as e:
        await interaction.followup.send(f"Failed to ban user: `{e}`", ephemeral=True)


@tree.command(name="kick", description="Kick a user from the server.")
@staff_only()
@app_commands.describe(user="User to kick", reason="Reason for the kick")
async def kick(interaction: discord.Interaction, user: discord.Member, reason: str):
    await interaction.response.defer(ephemeral=True)
    try:
        await user.kick(reason=f"{interaction.user} - {reason}")
        embed = discord.Embed(
            title="User Kicked",
            color=discord.Color.orange(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="User", value=f"{user} ({user.id})", inline=False)
        embed.add_field(name="Moderator", value=f"{interaction.user} ({interaction.user.id})", inline=False)
        embed.add_field(name="Reason", value=reason, inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)
        if interaction.guild:
            await send_log_embed(interaction.guild, embed)
    except Exception as e:
        await interaction.followup.send(f"Failed to kick user: `{e}`", ephemeral=True)


@tree.command(name="timeout", description="Timeout a user for a duration.")
@staff_only()
@app_commands.describe(
    user="User to timeout",
    duration_minutes="Duration in minutes",
    reason="Reason for the timeout",
)
async def timeout(
    interaction: discord.Interaction,
    user: discord.Member,
    duration_minutes: app_commands.Range[int, 1, 40320],  # up to 28 days
    reason: str,
):
    await interaction.response.defer(ephemeral=True)
    try:
        until = datetime.now(timezone.utc) + timedelta(minutes=duration_minutes)
        await user.timeout(until, reason=f"{interaction.user} - {reason}")
        embed = discord.Embed(
            title="User Timed Out",
            color=discord.Color.orange(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="User", value=f"{user} ({user.id})", inline=False)
        embed.add_field(name="Moderator", value=f"{interaction.user} ({interaction.user.id})", inline=False)
        embed.add_field(name="Duration", value=f"{duration_minutes} minutes", inline=False)
        embed.add_field(name="Reason", value=reason, inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)
        if interaction.guild:
            await send_log_embed(interaction.guild, embed)
    except Exception as e:
        await interaction.followup.send(f"Failed to timeout user: `{e}`", ephemeral=True)


@tree.command(name="purge", description="Purge messages in this channel (up to 5000).")
@staff_only()
@app_commands.describe(amount="Number of messages to delete (max 5000)")
async def purge(interaction: discord.Interaction, amount: app_commands.Range[int, 1, 5000]):
    channel = interaction.channel
    if not isinstance(channel, discord.TextChannel):
        await interaction.response.send_message("This command can only be used in text channels.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    try:
        deleted = await channel.purge(limit=amount + 1)  # +1 to include the command message
        count = len(deleted) - 1 if len(deleted) > 0 else 0

        embed = discord.Embed(
            title="Messages Purged",
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Channel", value=channel.mention, inline=False)
        embed.add_field(name="Moderator", value=f"{interaction.user} ({interaction.user.id})", inline=False)
        embed.add_field(name="Amount", value=str(count), inline=False)

        await interaction.followup.send(f"Deleted {count} messages.", ephemeral=True)
        if interaction.guild:
            await send_log_embed(interaction.guild, embed)
    except Exception as e:
        await interaction.followup.send(f"Failed to purge messages: `{e}`", ephemeral=True)


# ---- Role assign / remove ----

@tree.command(name="roleadd", description="Add a role to a user.")
@staff_only()
@app_commands.describe(user="User to give the role to", role="Role to add")
async def roleadd(interaction: discord.Interaction, user: discord.Member, role: discord.Role):
    await interaction.response.defer(ephemeral=True)
    try:
        await user.add_roles(role, reason=f"{interaction.user} - roleadd command")
        embed = discord.Embed(
            title="Role Added",
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="User", value=f"{user} ({user.id})", inline=False)
        embed.add_field(name="Role", value=f"{role.mention} ({role.id})", inline=False)
        embed.add_field(name="Moderator", value=f"{interaction.user} ({interaction.user.id})", inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)
        if interaction.guild:
            await send_log_embed(interaction.guild, embed)
    except Exception as e:
        await interaction.followup.send(f"Failed to add role: `{e}`", ephemeral=True)


@tree.command(name="roleremove", description="Remove a role from a user.")
@staff_only()
@app_commands.describe(user="User to remove the role from", role="Role to remove")
async def roleremove(interaction: discord.Interaction, user: discord.Member, role: discord.Role):
    await interaction.response.defer(ephemeral=True)
    try:
        await user.remove_roles(role, reason=f"{interaction.user} - roleremove command")
        embed = discord.Embed(
            title="Role Removed",
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="User", value=f"{user} ({user.id})", inline=False)
        embed.add_field(name="Role", value=f"{role.mention} ({role.id})", inline=False)
        embed.add_field(name="Moderator", value=f"{interaction.user} ({interaction.user.id})", inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)
        if interaction.guild:
            await send_log_embed(interaction.guild, embed)
    except Exception as e:
        await interaction.followup.send(f"Failed to remove role: `{e}`", ephemeral=True)


# ---- Polls ----

@tree.command(name="poll", description="Create a simple reaction poll.")
@staff_only()
@app_commands.describe(
    question="The poll question",
    option1="First option",
    option2="Second option",
    option3="Third option (optional)",
    option4="Fourth option (optional)",
)
async def poll(
    interaction: discord.Interaction,
    question: str,
    option1: str,
    option2: str,
    option3: str | None = None,
    option4: str | None = None,
):
    await interaction.response.defer()
    options = [option1, option2]
    if option3:
        options.append(option3)
    if option4:
        options.append(option4)

    emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣"]
    used = emojis[: len(options)]

    description_lines = []
    for emoji, opt in zip(used, options):
        description_lines.append(f"{emoji} {opt}")

    embed = discord.Embed(
        title="📊 Poll",
        description=f"**{question}**\n\n" + "\n".join(description_lines),
        color=discord.Color.blurple(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_footer(text=f"Poll created by {interaction.user}")

    msg = await interaction.followup.send(embed=embed, wait=True)
    for emoji in used:
        await msg.add_reaction(emoji)


# ================== ON READY ==================

@bot.event
async def on_ready():
    print(f"{bot.user} is online | Slash commands syncing...")
    init_db()

    guild = bot.get_guild(GUILD_ID)
    if guild:
        try:
            await tree.sync(guild=guild)
            print(f"Slash commands synced to guild {guild.name} ({guild.id})")
        except Exception as e:
            print(f"Failed to sync commands: {e}")
    else:
        try:
            await tree.sync()
            print("Slash commands synced globally.")
        except Exception as e:
            print(f"Failed to sync commands globally: {e}")

    bot.loop.create_task(update_member_count_task())


# ================== RUN ==================

if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("TOKEN environment variable is not set.")
    bot.run(TOKEN)
