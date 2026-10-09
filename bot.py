#!/usr/bin/env python3
import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

import os
import json
import random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


# =========================
# CONFIGURATION
# =========================

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
TIMEZONE = ZoneInfo("Europe/Sofia")

# Roles that will be pinged for homework reminders
REMINDER_ROLE_IDS = [
    1554489252761440347
]

# Your Discord server ID
GUILD_ID = 1472693125133897818
GUILD = discord.Object(id=GUILD_ID)

# =========================
# USER REGISTRY
# =========================

USERS_FILE = "users.json"
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0"))


def load_users():
    if not os.path.exists(USERS_FILE):
        return {"users": {}, "requests": []}

    try:
        with open(USERS_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

        data.setdefault("users", {})
        data.setdefault("requests", [])
        return data

    except (json.JSONDecodeError, OSError):
        raise RuntimeError(
            "users.json could not be read. "
            "Fix or restore it before continuing."
        )


def save_users(data):
    temp_file = USERS_FILE + ".tmp"

    with open(temp_file, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=4, ensure_ascii=False)

    os.replace(temp_file, USERS_FILE)


def record_request(interaction, action, details=""):
    data = load_users()
    user_id = str(interaction.user.id)
    now = datetime.now(TIMEZONE).isoformat()

    user = data["users"].get(user_id)

    if user is None:
        user = {
            "name": interaction.user.name,
            "display_name": interaction.user.display_name,
            "status": "pending",
            "first_seen": now,
            "approved_at": None,
            "approved_by": None
        }
        data["users"][user_id] = user
    else:
        user["name"] = interaction.user.name
        user["display_name"] = interaction.user.display_name
        user["last_seen"] = now

    data["requests"].append({
        "user_id": user_id,
        "name": interaction.user.name,
        "action": action,
        "details": details,
        "timestamp": now
    })

    save_users(data)
    return user["status"] == "approved"


async def check_authorization(interaction, action, details=""):
    approved = record_request(interaction, action, details)

    if interaction.user.id == ADMIN_USER_ID:
        return True

    if approved:
        return True

    await interaction.response.send_message(
        "⏳ Your request has been recorded, but you are not "
        "authorized to change homework yet. "
        "The administrator must approve your account first.",
        ephemeral=True
    )
    return False


def is_admin(interaction):
    return (
        ADMIN_USER_ID != 0
        and interaction.user.id == ADMIN_USER_ID
    )


def require_admin():
    async def predicate(interaction: discord.Interaction):
        if not is_admin(interaction):
            raise app_commands.CheckFailure(
                "Only the bot administrator can do this."
            )
        return True

    return app_commands.check(predicate)


# =========================
# BOT SETUP
# =========================

intents = discord.Intents.none()
intents.guilds = True


# =========================
# BOT CLASS
# =========================

class HomeworkBot(commands.Bot):
    async def setup_hook(self):
        self.tree.clear_commands(guild=GUILD)
        self.tree.copy_global_to(guild=GUILD)

        try:
            synced = await self.tree.sync()
            print(f"Synced {len(synced)} slash command(s)")
        except Exception as e:
            print(f"Error syncing commands: {e}")

        if not reminder_checker.is_running():
            reminder_checker.start()


bot = HomeworkBot(
    command_prefix="!",
    intents=intents
)


# =========================
# HOMEWORK STORAGE
# =========================

HOMEWORK_FILE = "homework.json"


def load_homework():
    if not os.path.exists(HOMEWORK_FILE):
        return []

    try:
        with open(HOMEWORK_FILE, "r", encoding="utf-8") as file:
            return json.load(file)
    except (json.JSONDecodeError, FileNotFoundError):
        return []


def save_homework():
    with open(HOMEWORK_FILE, "w", encoding="utf-8") as file:
        json.dump(
            homework_list,
            file,
            indent=4,
            ensure_ascii=False
        )


homework_list = load_homework()


# =========================
# ADMIN: APPROVE USER
# =========================

@bot.tree.command(
    name="approve_user",
    description="Approve a user to manage homework"
)
@app_commands.describe(user_id="The user's Discord ID")
@require_admin()
async def approve_user(
    interaction: discord.Interaction,
    user_id: str
):
    data = load_users()
    user = data["users"].get(user_id)

    if user is None:
        await interaction.response.send_message(
            "❌ User not found. They must submit a request first.",
            ephemeral=True
        )
        return

    user["status"] = "approved"
    user["approved_at"] = datetime.now(TIMEZONE).isoformat()
    user["approved_by"] = str(interaction.user.id)

    save_users(data)

    await interaction.response.send_message(
        f"✅ Approved **{user['display_name']}** "
        f"(ID: `{user_id}`). They can now manage homework.",
        ephemeral=True
    )


# =========================
# ADMIN: LIST USERS
# =========================

@bot.tree.command(
    name="list_users",
    description="List everyone who has submitted a request"
)
@require_admin()
async def list_users(interaction: discord.Interaction):
    data = load_users()

    if not data["users"]:
        await interaction.response.send_message(
            "No users have been registered yet.",
            ephemeral=True
        )
        return

    lines = []

    for user_id, user in data["users"].items():
        status = user.get("status", "pending")
        lines.append(
            f"**{user.get('display_name', user['name'])}** "
            f"— `{status}` — ID: `{user_id}`"
        )

    message = "\n".join(lines)

    for start in range(0, len(message), 1900):
        await interaction.followup.send(
            message[start:start + 1900],
            ephemeral=True
        ) if start else await interaction.response.send_message(
            message[start:start + 1900],
            ephemeral=True
        )


# =========================
# READY
# =========================

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")


# =========================
# ADD HOMEWORK
# =========================

@bot.tree.command(
    name="add_homework",
    description="Add homework"
)
@app_commands.describe(
    classname="The class of the students",
    subject="The subject",
    description="What homework needs to be done",
    due_date="Due date: DD-MM-YYYY HH:MM"
)
async def add_homework(
    interaction: discord.Interaction,
    classname: str,
    subject: str,
    description: str,
    due_date: str
):
    if not await check_authorization(
        interaction,
        "add_homework",
        f"{classname}: {subject} — {description}"
    ):
        return

    try:
        due_datetime = datetime.strptime(
            due_date,
            "%d-%m-%Y %H:%M"
        ).replace(
            tzinfo=TIMEZONE
        )
    except ValueError:
        await interaction.response.send_message(
            "❌ Invalid date format.\n\n"
            "Use:\n"
            "`DD-MM-YYYY HH:MM`\n\n"
            "Example:\n"
            "`01-02-2026 18:00`",
            ephemeral=True
        )
        return

    now = datetime.now(TIMEZONE)

    if due_datetime <= now:
        await interaction.response.send_message(
            "❌ The due date must be in the future.",
            ephemeral=True
        )
        return

    existing_ids = {hw["id"] for hw in homework_list}

    while True:
        random_id = random.randint(1000000, 10000000)
        if random_id not in existing_ids:
            break

    homework = {
        "id": random_id,
        "class": classname,
        "subject": subject,
        "description": description,
        "due_date": due_datetime.isoformat(),
        "reminded_24h": False,
        "reminded_12h": False
    }

    homework_list.append(homework)
    save_homework()

    await interaction.response.send_message(
        f"📚 **Homework added!**\n\n"
        f"**Class:** {classname}\n"
        f"**Subject:** {subject}\n"
        f"**Description:** {description}\n"
        f"**Due:** {due_datetime.strftime('%d/%m/%Y %H:%M')}"
    )


# =========================
# LIST HOMEWORK
# =========================

@bot.tree.command(
    name="list_homework",
    description="Show all homework"
)
async def list_homework(
    interaction: discord.Interaction
):
    now = datetime.now(TIMEZONE)
    upcoming = []

    for homework in homework_list:
        due = datetime.fromisoformat(homework["due_date"])
        if due > now:
            upcoming.append(homework)

    if not upcoming:
        await interaction.response.send_message(
            "✅ There is no upcoming homework."
        )
        return

    upcoming.sort(key=lambda x: x["due_date"])

    lines = []
    for homework in upcoming:
        due = datetime.fromisoformat(homework["due_date"])
        lines.append(
            f"**{homework['class']}**\n"
            f"📚 **{homework['subject']}**\n"
            f"└ 📝 {homework['description']}\n"
            f"└ ⏰ Due: `{due.strftime('%d/%m/%Y %H:%M')}`"
        )

    await interaction.response.send_message("\n\n".join(lines))


# =========================
# DELETE HOMEWORK
# =========================

@bot.tree.command(
    name="delete_homework",
    description="Delete homework by description"
)
@app_commands.describe(
    classname="Which class the homework is for",
    description="The exact homework description"
)
async def delete_homework(
    interaction: discord.Interaction,
    classname: str,
    description: str
):
    if not await check_authorization(
        interaction,
        "delete_homework",
        description
    ):
        return

    matches = [
        hw for hw in homework_list
        if hw["description"].lower() == description.lower()
    ]

    if not matches:
        await interaction.response.send_message(
            "❌ No homework with that description was found.",
            ephemeral=True
        )
        return

    homework = matches[0]
    homework_list.remove(homework)
    save_homework()

    await interaction.response.send_message(
        f"🗑️ **Homework deleted!**\n\n"
        f"**Subject:** {homework['subject']}\n"
        f"**Description:** {homework['description']}"
    )


# =========================
# CLEAR HOMEWORK
# =========================

@bot.tree.command(
    name="clear_homework",
    description="Delete all homework"
)
async def clear_homework(
    interaction: discord.Interaction
):
    if not await check_authorization(
        interaction,
        "clear_homework",
        "Clear all homework"
    ):
        return

    homework_list.clear()
    save_homework()

    await interaction.response.send_message(
        "🗑️ **All homework has been deleted.**"
    )


# =========================
# REMINDER SYSTEM
# =========================

@tasks.loop(minutes=1)
async def reminder_checker():
    now = datetime.now(TIMEZONE)

    guild = bot.get_guild(GUILD_ID)
    if guild is None:
        return

    channel = None
    for text_channel in guild.text_channels:
        permissions = text_channel.permissions_for(guild.me)
        if permissions.send_messages:
            channel = text_channel
            break

    if channel is None:
        return

    changed = False

    for homework in homework_list:
        due = datetime.fromisoformat(homework["due_date"])

        if now >= due:
            homework["reminded_24h"] = True
            homework["reminded_12h"] = True
            changed = True
            continue

        reminder_12h = due - timedelta(hours=12)
        if not homework["reminded_12h"] and now >= reminder_12h:
            await send_reminder(channel, homework, "12 hours")
            homework["reminded_12h"] = True
            homework["reminded_24h"] = True
            changed = True
            continue

        reminder_24h = due - timedelta(hours=24)
        if not homework["reminded_24h"] and now >= reminder_24h:
            await send_reminder(channel, homework, "24 hours")
            homework["reminded_24h"] = True
            changed = True

    if changed:
        save_homework()


@reminder_checker.before_loop
async def before_reminder_checker():
    await bot.wait_until_ready()


async def send_reminder(
    channel,
    homework,
    time_remaining
):
    mentions = []
    for role_id in REMINDER_ROLE_IDS:
        role = channel.guild.get_role(role_id)
        if role:
            mentions.append(role.mention)

    mention_text = " ".join(mentions)
    due = datetime.fromisoformat(homework["due_date"])

    message = (
        f"🔔 **HOMEWORK REMINDER**\n\n"
        f"{mention_text}\n\n"
        f"📚 **Subject:** {homework['subject']}\n"
        f"📝 **Description:** {homework['description']}\n"
        f"⏰ **Due:** {due.strftime('%d/%m/%Y %H:%M')}\n\n"
        f"⚠️ Due in **{time_remaining}**."
    )

    await channel.send(
        message,
        allowed_mentions=discord.AllowedMentions(roles=True)
    )


# =========================
# RUN BOT
# =========================

if not TOKEN:
    print("ERROR: DISCORD_TOKEN was not found in your .env file.")
else:
    bot.run(TOKEN)
