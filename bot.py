import os
import sqlite3
import re
from datetime import datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

# ----------------- CONFIG -----------------

load_dotenv()
TOKEN = os.getenv("TOKEN")

GUILD_ID = 1472748211038064832          # your guild ID
STAFF_ROLE_ID = 1472955865144365148     # staff role ID
LOG_CHANNEL_NAME = "bluehorizon-logs"   # log channel name
DB_PATH = "moderation.db"

OWNER_ID = 1190692291535446156          # you
BETA_ROLE_ID = 1473745556198260890      # real beta role ID

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
        pass


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
    if message.author.bot:
        return

    # Ignore replies completely
    if message.reference is not None:
        await bot.process_commands(message)
        return

    # ----------------- OWNERSHIP PING PROTECTION -----------------
    ownership_ids = {650411480017141770, 797497654451765279, 1190692291535446156}
    mentioned_ids = {user.id for user in message.mentions}

    if ownership_ids.intersection(mentioned_ids):
        embed = discord.Embed(
            title="Notice Regarding Pings",
            description=(
                "Please avoid pinging ownership unless absolutely necessary. "
                "They are often handling critical tasks and may not be available to respond immediately.\n\n"
                "Continued misuse of pings may result in moderation action."
            ),
            color=discord.Color.red()
        )
        embed.set_footer(text="Blue Horizon Moderation Team")
        await message.channel.send(embed=embed)

    await bot.process_commands(message)


# ----------------- LOGGING EVENTS -----------------

TARGET_USER_ID = OWNER_ID  # forward deleted log messages to you


@bot.event
async def on_message_delete(message: discord.Message):
    if not message.guild:
        return

    log_channel = get_log_channel(message.guild)
    if not log_channel:
        return

    # If the deleted message was a LOG MESSAGE posted by the bot → forward it
    if message.channel.id == log_channel.id and message.author.id == bot.user.id:
        try:
            target = await message.guild.fetch_member(TARGET_USER_ID)

            if message.embeds:
                for embed in message.embeds:
                    forwarded = embed.copy()
                    forwarded.title = "A Log Message Was Deleted"
                    await target.send(embed=forwarded)

            if message.content:
                await target.send(
                    f"A log message was deleted in {log_channel.mention}:\n\n{message.content}"
                )

        except Exception as e:
            print(f"Could not forward deleted log: {e}")

        return

    if message.author.bot:
        return

    embed = discord.Embed(
        title="Message Deleted",
        description=f"Message by {message.author.mention} was deleted",
        color=discord.Color.red(),
        timestamp=datetime.utcnow()
    )

    embed.add_field(name="Channel", value=message.channel.mention, inline=False)
    embed.add_field(name="Content", value=message.content or "No text", inline=False)

    if message.attachments:
        urls = "\n".join(a.url for a in message.attachments)
        embed.add_field(name="Attachments", value=urls, inline=False)
        embed.set_image(url=message.attachments[0].url)

    if message.author.avatar:
        embed.set_thumbnail(url=message.author.avatar.url)

    await log_channel.send(embed=embed)


@bot.event
async def on_message_edit(before: discord.Message, after: discord.Message):
    if before.author.bot or not before.guild:
        return
    if before.content == after.content and before.attachments == after.attachments:
        return

    log_channel = get_log_channel(before.guild)
    if not log_channel:
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

    if before.attachments:
        urls = "\n".join(a.url for a in before.attachments)
        embed.add_field(name="Old Attachments", value=urls, inline=False)

    if after.attachments:
        urls = "\n".join(a.url for a in after.attachments)
        embed.add_field(name="New Attachments", value=urls, inline=False)
        embed.set_image(url=after.attachments[0].url)

    if before.author.avatar:
        embed.set_thumbnail(url=before.author.avatar.url)

    await log_channel.send(embed=embed)


@bot.event
async def on_member_join(member: discord.Member):
    log_channel = get_log_channel(member.guild)
    if not log_channel:
        return

    embed = discord.Embed(
        title="Member Joined",
        description=f"{member.mention} joined the server",
        color=discord.Color.green(),
        timestamp=datetime.utcnow()
    )

    if member.avatar:
        embed.set_thumbnail(url=member.avatar.url)

    await log_channel.send(embed=embed)


@bot.event
async def on_member_remove(member: discord.Member):
    log_channel = get_log_channel(member.guild)
    if not log_channel:
        return

    embed = discord.Embed(
        title="Member Left",
        description=f"{member} left the server",
        color=discord.Color.dark_red(),
        timestamp=datetime.utcnow()
    )

    if member.avatar:
        embed.set_thumbnail(url=member.avatar.url)

    await log_channel.send(embed=embed)


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

    log_channel = get_log_channel(after.guild)
    if not log_channel:
        return

    before_set = set(before.roles)
    after_set = set(after.roles)

    added = after_set - before_set
    removed = before_set - after_set

    for role in added:
        if role.is_default():
            continue

        embed = discord.Embed(
            title="Role Assigned",
            color=discord.Color.green(),
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="User", value=after.mention, inline=False)
        embed.add_field(name="Role", value=role.mention, inline=False)

        await log_channel.send(embed=embed)

    for role in removed:
        if role.is_default():
            continue

        embed = discord.Embed(
            title="Role Removed",
            color=discord.Color.red(),
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="User", value=after.mention, inline=False)
        embed.add_field(name="Role", value=role.mention, inline=False)

        await log_channel.send(embed=embed)


# ----------------- SLASH COMMANDS -----------------

guild_obj = discord.Object(id=GUILD_ID)


@tree.command(name="ping", description="Check if the bot is alive.", guild=guild_obj)
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("Pong.", ephemeral=True)


# ----------------- MODERATION: TIMEOUT -----------------

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


# ----------------- MODERATION: UNTIMEOUT -----------------

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


# ----------------- MODERATION: BAN -----------------

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


# ----------------- MODERATION: KICK -----------------

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


# ----------------- MODERATION: WARN -----------------

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


# ----------------- MODERATION: HISTORY -----------------

@tree.command(name="history", description="View a user's moderation history.", guild=guild_obj)
@staff_only()
@app_commands.describe(
    user="User to view history for"
)
async def history(
    interaction: discord.Interaction,
    user: discord.Member
):
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
            value=f"Moderator: <@{mod_id}>\nReason: {reason}\nTime: {ts}",
            inline=False
        )

    await interaction.response.send_message(embed=embed, ephemeral=True)


# ----------------- MODERATION: REVOKE CASE -----------------

@tree.command(name="revoke", description="Revoke a specific moderation case.", guild=guild_obj)
@staff_only()
@app_commands.describe(
    case_id="The case ID to revoke"
)
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


# ----------------- MODERATION: CLEAR HISTORY -----------------

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


# ----------------- ANNOUNCE (TEXT ONLY) -----------------

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
    await channel.send(message)

    await interaction.response.send_message(
        f"Announcement sent in {channel.mention}.",
        ephemeral=True
    )


# ----------------- ROLEASSIGN -----------------

@tree.command(name="roleassign", description="Assign or remove a role from a user.", guild=guild_obj)
@staff_only()
@app_commands.describe(
    user="User to modify",
    role="Role to assign or remove"
)
async def roleassign(interaction: discord.Interaction, user: discord.Member, role: discord.Role):

    if role in user.roles:
        await user.remove_roles(role, reason=f"Removed by {interaction.user}")
        action = "removed"
    else:
        await user.add_roles(role, reason=f"Assigned by {interaction.user}")
        action = "assigned"

    log_channel = get_log_channel(interaction.guild)
    if log_channel:
        embed = discord.Embed(
            title="Role Updated",
            color=discord.Color.blurple(),
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="User", value=user.mention, inline=False)
        embed.add_field(name="Role", value=role.mention, inline=False)
        embed.add_field(name="Action", value=action, inline=False)
        embed.add_field(name="Moderator", value=interaction.user.mention, inline=False)
        await log_channel.send(embed=embed)

    await interaction.response.send_message(
        f"Role {role.name} has been {action} for {user.mention}.",
        ephemeral=True
    )


# ----------------- BETA ACCESS -----------------

@tree.command(name="beta", description="Give a user access to the beta category.", guild=guild_obj)
@app_commands.describe(
    user="User to give beta access to"
)
async def beta(interaction: discord.Interaction, user: discord.Member):

    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("You are not allowed to use this command.", ephemeral=True)
        return

    beta_role = interaction.guild.get_role(BETA_ROLE_ID)
    if not beta_role:
        await interaction.response.send_message("Beta role not found. Update BETA_ROLE_ID.", ephemeral=True)
        return

    await user.add_roles(beta_role, reason=f"Beta access granted by {interaction.user}")

    await interaction.response.send_message(
        f"{user.mention} has been granted Beta Access.",
        ephemeral=True
    )

    log_channel = get_log_channel(interaction.guild)
    if log_channel:
        embed = discord.Embed(
            title="Beta Access Granted",
            color=discord.Color.blurple(),
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="User", value=user.mention, inline=False)
        embed.add_field(name="Granted By", value=interaction.user.mention, inline=False)
        embed.add_field(name="Role", value=beta_role.mention, inline=False)
        await log_channel.send(embed=embed)


# ----------------- ADVANCED PURGE -----------------

@tree.command(name="purge", description="Advanced message purge system.", guild=guild_obj)
@staff_only()
@app_commands.describe(
    amount="How many messages to delete (1–5000)",
    user="Only delete messages from this user",
    contains="Only delete messages containing this text",
    bots="Delete only bot messages",
    images="Delete only messages with attachments",
    after="Delete messages after this message link"
)
async def purge(
    interaction: discord.Interaction,
    amount: int,
    user: discord.Member | None = None,
    contains: str | None = None,
    bots: bool = False,
    images: bool = False,
    after: str | None = None
):

    await interaction.response.defer(ephemeral=True)

    if amount < 1 or amount > 5000:
        await interaction.followup.send("Amount must be between 1 and 5000.", ephemeral=True)
        return

    after_message = None
    if after:
        try:
            parts = after.split("/")
            msg_id = int(parts[-1])
            after_message = await interaction.channel.fetch_message(msg_id)
        except:
            await interaction.followup.send("Invalid message link.", ephemeral=True)
            return

    def check(msg: discord.Message):
        if after_message and msg.id <= after_message.id:
            return False
        if user and msg.author != user:
            return False
        if contains and contains.lower() not in msg.content.lower():
            return False
        if bots and not msg.author.bot:
            return False
        if images and not msg.attachments:
            return False
        return True

    deleted_total = 0
    remaining = amount

    while remaining > 0:
        batch_size = min(remaining, 100)
        deleted = await interaction.channel.purge(limit=batch_size, check=check)
        if not deleted:
            break
        deleted_total += len(deleted)
        remaining -= len(deleted)

    log_channel = get_log_channel(interaction.guild)
    if log_channel:
        embed = discord.Embed(
            title="Messages Purged",
            color=discord.Color.dark_red(),
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Moderator", value=interaction.user.mention, inline=False)
        embed.add_field(name="Channel", value=interaction.channel.mention, inline=False)
        embed.add_field(name="Amount", value=str(deleted_total), inline=False)

        if user:
            embed.add_field(name="Filtered User", value=user.mention, inline=False)
        if contains:
            embed.add_field(name="Contains", value=contains, inline=False)
        if bots:
            embed.add_field(name="Bots Only", value="True", inline=False)
        if images:
            embed.add_field(name="Images Only", value="True", inline=False)
        if after_message:
            embed.add_field(name="After Message", value=f"[Jump]({after})", inline=False)

        await log_channel.send(embed=embed)

    await interaction.followup.send(
        f"Purged {deleted_total} messages.",
        ephemeral=True
    )


# ----------------- RUN -----------------

bot.run(TOKEN)


