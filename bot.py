import os
import sqlite3
import re
from datetime import datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
import aiohttp

async def send_webhook_log(message: str):
    url = os.getenv("WEBHOOK_URL")
    if not url:
        return

    async with aiohttp.ClientSession() as session:
        await session.post(url, json={"content": message})
# ----------------- CONFIG -----------------

load_dotenv()
TOKEN = os.getenv("TOKEN")

GUILD_ID = 1472748211038064832
STAFF_ROLE_ID = 1472955865144365148
LOG_CHANNEL_NAME = "bluehorizon-logs"
DB_PATH = "moderation.db"

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree


# ----------------- DATABASE -----------------

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            moderator_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            reason TEXT,
            timestamp TEXT NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS warnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            moderator_id INTEGER NOT NULL,
            reason TEXT,
            timestamp TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()


def add_case(user_id: int, moderator_id: int, action: str, reason: str | None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    ts = datetime.utcnow().isoformat()
    c.execute(
        "INSERT INTO cases (user_id, moderator_id, action, reason, timestamp) VALUES (?, ?, ?, ?, ?)",
        (user_id, moderator_id, action, reason, ts),
    )
    case_id = c.lastrowid
    conn.commit()
    conn.close()
    return case_id


def add_warning(user_id: int, moderator_id: int, reason: str | None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    ts = datetime.utcnow().isoformat()
    c.execute(
        "INSERT INTO warnings (user_id, moderator_id, reason, timestamp) VALUES (?, ?, ?, ?)",
        (user_id, moderator_id, reason, ts),
    )
    warning_id = c.lastrowid
    conn.commit()
    conn.close()
    return warning_id


def get_history(user_id: int, limit: int = 10):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT id, action, reason, moderator_id, timestamp FROM cases WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (user_id, limit),
    )
    rows = c.fetchall()
    conn.close()
    return rows


# ----------------- HELPERS -----------------

def get_log_channel(guild: discord.Guild):
    return discord.utils.get(guild.channels, name=LOG_CHANNEL_NAME)


def parse_duration(duration: str) -> timedelta | None:
    match = re.fullmatch(r"(\d+)([smhdw])", duration.lower().strip())
    if not match:
        return None

    value = int(match.group(1))
    unit = match.group(2)

    if unit == "s":
        return timedelta(seconds=value)
    if unit == "m":
        return timedelta(minutes=value)
    if unit == "h":
        return timedelta(hours=value)
    if unit == "d":
        return timedelta(days=value)
    if unit == "w":
        return timedelta(weeks=value)
    return None


async def send_dm(user: discord.User, embed: discord.Embed):
    try:
        await user.send(embed=embed)
    except:
        pass  # ignore closed DMs


def staff_only():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            return False
        member = interaction.user
        if not isinstance(member, discord.Member):
            return False
        return any(role.id == STAFF_ROLE_ID for role in member.roles)
    return app_commands.check(predicate)


# ----------------- EVENTS -----------------

@bot.event
async def on_ready():
    init_db()
    guild = discord.Object(id=GUILD_ID)
    await tree.sync(guild=guild)
    print(f"Blue Horizon is online as {bot.user} | Slash commands synced.")


@bot.event
async def on_message(message: discord.Message):
    if isinstance(message.channel, discord.DMChannel):
        return
    await bot.process_commands(message)


# ----------------- LOGGING EVENTS -----------------

@bot.event
async def on_message_delete(message: discord.Message):
    if message.author.bot or not message.guild:
        return
    channel = get_log_channel(message.guild)
    if not channel:
        return

    embed = discord.Embed(
        title="Message Deleted",
        description=f"Message by {message.author.mention} was deleted",
        color=discord.Color.red(),
        timestamp=datetime.utcnow()
    )
    embed.add_field(name="Channel", value=message.channel.mention, inline=False)
    embed.add_field(name="Content", value=message.content or "No text", inline=False)
    if message.author.avatar:
        embed.set_thumbnail(url=message.author.avatar.url)
    await channel.send(embed=embed)


@bot.event
async def on_message_edit(before: discord.Message, after: discord.Message):
    if before.author.bot or not before.guild:
        return
    if before.content == after.content:
        return

    channel = get_log_channel(before.guild)
    if not channel:
        return

    embed = discord.Embed(
        title="Message Edited",
        description=f"{before.author.mention} edited a message",
        color=discord.Color.orange(),
        timestamp=datetime.utcnow()
    )
    embed.add_field(name="Channel", value=before.channel.mention, inline=False)
    embed.add_field(name="Before", value=before.content or "No text", inline=False)
    embed.add_field(name="After", value=after.content or "No text", inline=False)
    if before.author.avatar:
        embed.set_thumbnail(url=before.author.avatar.url)
    await channel.send(embed=embed)


@bot.event
async def on_member_join(member: discord.Member):
    channel = get_log_channel(member.guild)
    if not channel:
        return
    embed = discord.Embed(
        title="Member Joined",
        description=f"{member.mention} joined the server",
        color=discord.Color.green(),
        timestamp=datetime.utcnow()
    )
    if member.avatar:
        embed.set_thumbnail(url=member.avatar.url)
    await channel.send(embed=embed)


@bot.event
async def on_member_remove(member: discord.Member):
    channel = get_log_channel(member.guild)
    if not channel:
        return
    embed = discord.Embed(
        title="Member Left",
        description=f"{member} left the server",
        color=discord.Color.dark_red(),
        timestamp=datetime.utcnow()
    )
    if member.avatar:
        embed.set_thumbnail(url=member.avatar.url)
    await channel.send(embed=embed)


@bot.event
async def on_guild_channel_create(channel: discord.abc.GuildChannel):
    log_channel = get_log_channel(channel.guild)
    if not log_channel:
        return
    embed = discord.Embed(
        title="Channel Created",
        description=f"{channel.mention} was created",
        color=discord.Color.green(),
        timestamp=datetime.utcnow()
    )
    await log_channel.send(embed=embed)


@bot.event
async def on_guild_channel_delete(channel: discord.abc.GuildChannel):
    log_channel = get_log_channel(channel.guild)
    if not log_channel:
        return
    embed = discord.Embed(
        title="Channel Deleted",
        description=f"{channel.name} was deleted",
        color=discord.Color.dark_red(),
        timestamp=datetime.utcnow()
    )
    await log_channel.send(embed=embed)


@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    if before.roles == after.roles:
        return

    guild = after.guild
    channel = get_log_channel(guild)
    if not channel:
        return

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
                description=f"{after.mention} was given a role",
                color=discord.Color.blurple(),
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="Role", value=role.mention, inline=False)
            await channel.send(embed=embed)

    if removed:
        for role in removed:
            if role.is_default():
                continue
            embed = discord.Embed(
                title="Role Removed",
                description=f"{after.mention} lost a role",
                color=discord.Color.dark_grey(),
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="Role", value=role.mention, inline=False)
            await channel.send(embed=embed)


# ----------------- SLASH COMMANDS -----------------

guild_obj = discord.Object(id=GUILD_ID)


@tree.command(name="ping", description="Check if the bot is alive.", guild=guild_obj)
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("Pong!", ephemeral=True)


# ----------------- TIMEOUT -----------------

@tree.command(name="timeout", description="Timeout a member for a duration.", guild=guild_obj)
@staff_only()
@app_commands.describe(
    user="User to timeout",
    duration="Duration (e.g. 10m, 2h, 1d, 1w, 30s)",
    reason="Reason for the timeout"
)
async def timeout(
    interaction: discord.Interaction,
    user: discord.Member,
    duration: str,
    reason: str = "No reason provided"
):
    delta = parse_duration(duration)
    if not delta:
        await interaction.response.send_message(
            "Invalid duration. Use one unit: `Xs`, `Xm`, `Xh`, `Xd`, `Xw`.",
            ephemeral=True
        )
        return

    try:
        await user.timeout(delta, reason=reason)
    except discord.Forbidden:
        await interaction.response.send_message("I don't have permission to timeout that user.", ephemeral=True)
        return

    case_id = add_case(user.id, interaction.user.id, "timeout", f"{reason} (duration: {duration})")

    dm_embed = discord.Embed(
        title="You have been timed out",
        color=discord.Color.dark_grey(),
        timestamp=datetime.utcnow()
    )
    dm_embed.add_field(name="Duration", value=duration, inline=False)
    dm_embed.add_field(name="Reason", value=reason, inline=False)
    dm_embed.add_field(name="Case ID", value=str(case_id), inline=False)
    await send_dm(user, dm_embed)

    log_channel = get_log_channel(interaction.guild)
    if log_channel:
        embed = discord.Embed(
            title=f"User Timed Out | Case #{case_id}",
            color=discord.Color.dark_grey(),
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="User", value=f"{user} ({user.mention})", inline=False)
        embed.add_field(name="Moderator", value=interaction.user.mention, inline=False)
        embed.add_field(name="Duration", value=duration, inline=False)
        embed.add_field(name="Reason", value=reason, inline=False)
        await log_channel.send(embed=embed)

    await interaction.response.send_message(
        f"{user.mention} has been timed out for `{duration}`. Case `#{case_id}`.",
        ephemeral=True
    )


# ----------------- UNTIMEOUT -----------------

@tree.command(name="untimeout", description="Remove timeout from a member.", guild=guild_obj)
@staff_only()
@app_commands.describe(
    user="User to remove timeout from",
    reason="Reason for removing timeout"
)
async def untimeout(
    interaction: discord.Interaction,
    user: discord.Member,
    reason: str = "No reason provided"
):
    try:
        await user.timeout(None, reason=reason)
    except discord.Forbidden:
        await interaction.response.send_message("I don't have permission to untimeout that user.", ephemeral=True)
        return

    case_id = add_case(user.id, interaction.user.id, "untimeout", reason)

    dm_embed = discord.Embed(
        title="Your timeout has been removed",
        color=discord.Color.blue(),
        timestamp=datetime.utcnow()
    )
    dm_embed.add_field(name="Reason", value=reason, inline=False)
    dm_embed.add_field(name="Case ID", value=str(case_id), inline=False)
    await send_dm(user, dm_embed)

    log_channel = get_log_channel(interaction.guild)
    if log_channel:
        embed = discord.Embed(
            title=f"Timeout Removed | Case #{case_id}",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="User", value=f"{user} ({user.mention})", inline=False)
        embed.add_field(name="Moderator", value=interaction.user.mention, inline=False)
        embed.add_field(name="Reason", value=reason, inline=False)
        await log_channel.send(embed=embed)

    await interaction.response.send_message(
        f"Timeout removed from {user.mention}. Case `#{case_id}`.",
        ephemeral=True
    )


# ----------------- BAN -----------------

@tree.command(name="ban", description="Ban a member.", guild=guild_obj)
@staff_only()
@app_commands.describe(
    user="User to ban",
    reason="Reason for the ban"
)
async def ban(
    interaction: discord.Interaction,
    user: discord.Member,
    reason: str = "No reason provided"
):
    try:
        await interaction.guild.ban(user, reason=reason, delete_message_days=0)
    except discord.Forbidden:
        await interaction.response.send_message("I don't have permission to ban that user.", ephemeral=True)
        return

    case_id = add_case(user.id, interaction.user.id, "ban", reason)

    dm_embed = discord.Embed(
        title="You have been banned",
        color=discord.Color.red(),
        timestamp=datetime.utcnow()
    )
    dm_embed.add_field(name="Reason", value=reason, inline=False)
    dm_embed.add_field(name="Case ID", value=str(case_id), inline=False)
    await send_dm(user, dm_embed)

    log_channel = get_log_channel(interaction.guild)
    if log_channel:
        embed = discord.Embed(
            title=f"User Banned | Case #{case_id}",
            color=discord.Color.red(),
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="User", value=f"{user} ({user.mention})", inline=False)
        embed.add_field(name="Moderator", value=interaction.user.mention, inline=False)
        embed.add_field(name="Reason", value=reason, inline=False)
        await log_channel.send(embed=embed)

    await interaction.response.send_message(
        f"{user.mention} has been banned. Case `#{case_id}`.",
        ephemeral=True
    )


# ----------------- KICK -----------------

@tree.command(name="kick", description="Kick a member.", guild=guild_obj)
@staff_only()
@app_commands.describe(
    user="User to kick",
    reason="Reason for the kick"
)
async def kick(
    interaction: discord.Interaction,
    user: discord.Member,
    reason: str = "No reason provided"
):
    try:
        await user.kick(reason=reason)
    except discord.Forbidden:
        await interaction.response.send_message("I don't have permission to kick that user.", ephemeral=True)
        return

    case_id = add_case(user.id, interaction.user.id, "kick", reason)

    dm_embed = discord.Embed(
        title="You have been kicked",
        color=discord.Color.orange(),
        timestamp=datetime.utcnow()
    )
    dm_embed.add_field(name="Reason", value=reason, inline=False)
    dm_embed.add_field(name="Case ID", value=str(case_id), inline=False)
    await send_dm(user, dm_embed)

    log_channel = get_log_channel(interaction.guild)
    if log_channel:
        embed = discord.Embed(
            title=f"User Kicked | Case #{case_id}",
            color=discord.Color.orange(),
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="User", value=f"{user} ({user.mention})", inline=False)
        embed.add_field(name="Moderator", value=interaction.user.mention, inline=False)
        embed.add_field(name="Reason", value=reason, inline=False)
        await log_channel.send(embed=embed)

    await interaction.response.send_message(
        f"{user.mention} has been kicked. Case `#{case_id}`.",
        ephemeral=True
    )


# ----------------- WARN -----------------

@tree.command(name="warn", description="Warn a member.", guild=guild_obj)
@staff_only()
@app_commands.describe(
    user="User to warn",
    reason="Reason for the warning"
)
async def warn(
    interaction: discord.Interaction,
    user: discord.Member,
    reason: str = "No reason provided"
):
    warning_id = add_warning(user.id, interaction.user.id, reason)
    case_id = add_case(user.id, interaction.user.id, "warn", reason)

    dm_embed = discord.Embed(
        title="You have received a warning",
        color=discord.Color.gold(),
        timestamp=datetime.utcnow()
    )
    dm_embed.add_field(name="Reason", value=reason, inline=False)
    dm_embed.add_field(name="Case ID", value=str(case_id), inline=False)
    dm_embed.add_field(name="Warning ID", value=str(warning_id), inline=False)
    await send_dm(user, dm_embed)

    log_channel = get_log_channel(interaction.guild)
    if log_channel:
        embed = discord.Embed(
            title=f"User Warned | Case #{case_id}",
            color=discord.Color.gold(),
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="User", value=f"{user} ({user.mention})", inline=False)
        embed.add_field(name="Moderator", value=interaction.user.mention, inline=False)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(name="Warning ID", value=str(warning_id), inline=False)
        await log_channel.send(embed=embed)

    await interaction.response.send_message(
        f"{user.mention} has been warned. Case `#{case_id}`, Warning `#{warning_id}`.",
        ephemeral=True
    )


# ----------------- HISTORY -----------------

class HistoryButtons(discord.ui.View):
    def __init__(self, user: discord.Member):
        super().__init__(timeout=None)
        self.user = user

    @discord.ui.button(label="Clear All History", style=discord.ButtonStyle.danger)
    async def clear_all(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not any(role.id == STAFF_ROLE_ID for role in interaction.user.roles):
            await interaction.response.send_message("You do not have permission.", ephemeral=True)
            return

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("DELETE FROM cases WHERE user_id = ?", (self.user.id,))
        conn.commit()
        conn.close()

        await interaction.response.send_message(
            f"All history for {self.user.mention} has been cleared.",
            ephemeral=True
        )


@tree.command(name="history", description="View a user's moderation history.", guild=guild_obj)
@staff_only()
@app_commands.describe(
    user="User to view history for"
)
async def history(interaction: discord.Interaction, user: discord.Member):
    rows = get_history(user.id, limit=10)
    if not rows:
        await interaction.response.send_message(
            f"No moderation history found for {user.mention}.",
            ephemeral=True
        )
        return

    embed = discord.Embed(
        title=f"Moderation History for {user}",
        color=discord.Color.blurple(),
        timestamp=datetime.utcnow()
    )

    for case_id, action, reason, mod_id, ts in rows:
        embed.add_field(
            name=f"Case #{case_id} | {action.upper()}",
            value=f"**Moderator:** <@{mod_id}>\n**Reason:** {reason}\n**Time:** {ts}",
            inline=False
        )

    view = HistoryButtons(user)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


# ----------------- POLL -----------------

POLL_EMOJIS = ["🅰️", "🅱️", "🇨", "🇩", "🇪", "🇫", "🇬", "🇭", "🇮", "🇯"]


@tree.command(name="poll", description="Create a reaction-based poll.", guild=guild_obj)
@staff_only()
@app_commands.describe(
    question="The poll question",
    options="Comma-separated options (max 10)"
)
async def poll(
    interaction: discord.Interaction,
    question: str,
    options: str
):
    opts = [o.strip() for o in options.split(",") if o.strip()]
    if len(opts) < 2:
        await interaction.response.send_message(
            "You need at least 2 options.",
            ephemeral=True
        )
        return
    if len(opts) > 10:
        await interaction.response.send_message(
            "Maximum of 10 options allowed.",
            ephemeral=True
        )
        return

    embed = discord.Embed(
        title="Poll",
        description=question,
        color=discord.Color.blurple(),
        timestamp=datetime.utcnow()
    )

    desc_lines = []
    for i, option in enumerate(opts):
        desc_lines.append(f"{POLL_EMOJIS[i]} — {option}")
    embed.add_field(name="Options", value="\n".join(desc_lines), inline=False)
    embed.set_footer(text=f"Poll by {interaction.user}", icon_url=interaction.user.display_avatar.url)

    await interaction.response.send_message("Poll created.", ephemeral=True)
    msg = await interaction.channel.send(embed=embed)

    for i in range(len(opts)):
        await msg.add_reaction(POLL_EMOJIS[i])


# ----------------- ANNOUNCE -----------------

@tree.command(name="announce", description="Send an announcement to any channel.", guild=guild_obj)
@staff_only()
@app_commands.describe(
    channel="Channel to send the announcement in",
    message="The announcement content"
)
async def announce(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    message: str
):
    embed = discord.Embed(
        title="Announcement",
        description=message,
        color=discord.Color.blurple(),
        timestamp=datetime.utcnow()
    )
    embed.set_footer(text=f"Announcement by {interaction.user}", icon_url=interaction.user.display_avatar.url)

    await channel.send(embed=embed)
    await channel.send(message)

    await interaction.response.send_message(
        f"Announcement sent in {channel.mention}.",
        ephemeral=True
    )
@tree.command(name="revoke", description="Revoke a specific moderation case.", guild=guild_obj)
@staff_only()
@app_commands.describe(
    case_id="The case ID to revoke"
)

# ----------------- REVOKE CASE -----------------

async def revoke(interaction: discord.Interaction, case_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("SELECT user_id, action, reason FROM cases WHERE id = ?", (case_id,))
    row = c.fetchone()

    if not row:
        await interaction.response.send_message("Case not found.", ephemeral=True)
        conn.close()
        return

    user_id, action, reason = row

    c.execute("DELETE FROM cases WHERE id = ?", (case_id,))
    conn.commit()
    conn.close()

    await interaction.response.send_message(
        f"Case #{case_id} has been revoked.",
        ephemeral=True
    )
# ----------------- CLEAR HISTORY -----------------

@tree.command(name="clearhistory", description="Clear all moderation history for a user.", guild=guild_obj)
@staff_only()
@app_commands.describe(
    user="User whose history will be cleared"
)
async def clearhistory(interaction: discord.Interaction, user: discord.Member):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("DELETE FROM cases WHERE user_id = ?", (user.id,))
    conn.commit()
    conn.close()

    await interaction.response.send_message(
        f"All moderation history for {user.mention} has been cleared.",
        ephemeral=True
    )

# ----------------- RUN -----------------
await send_webhook_log("🚀 Blue Horizon is now online.")

bot.run(TOKEN)

