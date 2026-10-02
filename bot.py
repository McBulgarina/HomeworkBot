#!/bin/bash
import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

import os
import json
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
# BOT SETUP
# =========================

intents = discord.Intents.none()
intents.guilds = True


# =========================
# HOMEWORK STORAGE
# =========================

HOMEWORK_FILE = "homework.json"


def load_homework():

    if not os.path.exists(HOMEWORK_FILE):
        return []

    try:

        with open(
            HOMEWORK_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            return json.load(file)

    except (json.JSONDecodeError, FileNotFoundError):

        return []


def save_homework():

    with open(
        HOMEWORK_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            homework_list,
            file,
            indent=4,
            ensure_ascii=False
        )


homework_list = load_homework()


# =========================
# BOT CLASS
# =========================

class HomeworkBot(commands.Bot):

    async def setup_hook(self):

        # Remove old commands from this server
        self.tree.clear_commands(guild=GUILD)

        # Copy all commands registered on the bot
        # to this specific server.
        self.tree.copy_global_to(guild=GUILD)

        try:
            synced = await self.tree.sync( )

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
# READY
# =========================

@bot.event
async def on_ready():

    print(
        f"Logged in as {bot.user}"
    )


# =========================
# ADD HOMEWORK
# =========================

@bot.tree.command(
    name="add_homework",
    description="Add homework",
     
)
@app_commands.describe(
    subject="The subject",
    description="What homework needs to be done",
    due_date="Due date: YYYY-MM-DD HH:MM"
)
async def add_homework(
    interaction: discord.Interaction,
    subject: str,
    description: str,
    due_date: str
):

    # =========================
    # CONVERT DATE
    # =========================

    try:

        due_datetime = datetime.strptime(
            due_date,
            "%Y-%m-%d %H:%M"
        ).replace(
            tzinfo=TIMEZONE
        )

    except ValueError:

        await interaction.response.send_message(

            "❌ Invalid date format.\n\n"
            "Use:\n"
            "`YYYY-MM-DD HH:MM`\n\n"
            "Example:\n"
            "`2026-10-01 18:00`",

            ephemeral=True
        )

        return


    # =========================
    # CHECK DATE
    # =========================

    now = datetime.now(
        TIMEZONE
    )

    if due_datetime <= now:

        await interaction.response.send_message(

            "❌ The due date must be in the future.",

            ephemeral=True
        )

        return


    # =========================
    # CREATE HOMEWORK
    # =========================

    homework = {

        "id": len(homework_list) + 1,

        "subject": subject,

        "description": description,

        "due_date": due_datetime.isoformat(),

        "reminded_24h": False,

        "reminded_12h": False
    }


    homework_list.append(
        homework
    )

    save_homework()


    # =========================
    # RESPONSE
    # =========================

    await interaction.response.send_message(

        f"📚 **Homework added!**\n\n"

        f"**Subject:** {subject}\n"

        f"**Description:** {description}\n"

        f"**Due:** "
        f"{due_datetime.strftime('%d/%m/%Y %H:%M')}"
    )


# =========================
# LIST HOMEWORK
# =========================

@bot.tree.command(
    name="list_homework",
    description="Show all homework",
     
)
async def list_homework(
    interaction: discord.Interaction
):

    now = datetime.now(
        TIMEZONE
    )


    upcoming = []


    for homework in homework_list:

        due = datetime.fromisoformat(
            homework["due_date"]
        )

        if due > now:

            upcoming.append(
                homework
            )


    # =========================
    # NO HOMEWORK
    # =========================

    if not upcoming:

        await interaction.response.send_message(

            "✅ There is no upcoming homework."

        )

        return


    # =========================
    # SORT
    # =========================

    upcoming.sort(
        key=lambda x: x["due_date"]
    )


    # =========================
    # CREATE MESSAGE
    # =========================

    lines = []


    for homework in upcoming:

        due = datetime.fromisoformat(
            homework["due_date"]
        )


        lines.append(

            f"📚 **{homework['subject']}**\n"

            f"└ 📝 {homework['description']}\n"

            f"└ ⏰ Due: "
            f"`{due.strftime('%d/%m/%Y %H:%M')}`"

        )


    await interaction.response.send_message(

        "\n\n".join(lines)

    )


# =========================
# DELETE HOMEWORK
# =========================

@bot.tree.command(
    name="delete_homework",
    description="Delete homework by description",
     
)
@app_commands.describe(
    description="The exact homework description"
)
async def delete_homework(
    interaction: discord.Interaction,
    description: str
):

    # Find matching homework

    matches = [

        homework

        for homework in homework_list

        if homework["description"].lower()
        == description.lower()

    ]


    # =========================
    # NOT FOUND
    # =========================

    if not matches:

        await interaction.response.send_message(

            "❌ No homework with that description "
            "was found.",

            ephemeral=True
        )

        return


    # =========================
    # DELETE
    # =========================

    homework = matches[0]

    homework_list.remove(
        homework
    )

    save_homework()


    await interaction.response.send_message(

        f"🗑️ **Homework deleted!**\n\n"

        f"**Subject:** "
        f"{homework['subject']}\n"

        f"**Description:** "
        f"{homework['description']}"

    )


# =========================
# CLEAR HOMEWORK
# =========================

@bot.tree.command(
    name="clear_homework",
    description="Delete all homework",
     
)
async def clear_homework(
    interaction: discord.Interaction
):

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

    now = datetime.now(
        TIMEZONE
    )


    # =========================
    # FIND SERVER
    # =========================

    guild = bot.get_guild(
        GUILD_ID
    )

    if guild is None:

        return


    # =========================
    # FIND CHANNEL
    # =========================

    channel = None


    for text_channel in guild.text_channels:

        permissions = text_channel.permissions_for(
            guild.me
        )

        if permissions.send_messages:

            channel = text_channel

            break


    if channel is None:

        return


    changed = False


    # =========================
    # CHECK HOMEWORK
    # =========================

    for homework in homework_list:

        due = datetime.fromisoformat(
            homework["due_date"]
        )


        # =========================
        # HOMEWORK ALREADY DUE
        # =========================

        if now >= due:

            homework["reminded_24h"] = True
            homework["reminded_12h"] = True

            changed = True

            continue


        # =========================
        # 12 HOUR REMINDER
        # =========================

        reminder_12h = (
            due - timedelta(hours=12)
        )


        if (
            not homework["reminded_12h"]
            and now >= reminder_12h
        ):

            await send_reminder(

                channel,

                homework,

                "12 hours"

            )

            homework["reminded_12h"] = True

            # Don't send an old 24h reminder
            # if we're already inside the 12h window.

            homework["reminded_24h"] = True

            changed = True

            continue


        # =========================
        # 24 HOUR REMINDER
        # =========================

        reminder_24h = (
            due - timedelta(hours=24)
        )


        if (
            not homework["reminded_24h"]
            and now >= reminder_24h
        ):

            await send_reminder(

                channel,

                homework,

                "24 hours"

            )

            homework["reminded_24h"] = True

            changed = True


    # =========================
    # SAVE CHANGES
    # =========================

    if changed:

        save_homework()


# =========================
# REMINDER LOOP STARTUP
# =========================

@reminder_checker.before_loop
async def before_reminder_checker():

    await bot.wait_until_ready()


# =========================
# SEND REMINDER
# =========================

async def send_reminder(
    channel,
    homework,
    time_remaining
):

    mentions = []


    # =========================
    # ROLE MENTIONS
    # =========================

    for role_id in REMINDER_ROLE_IDS:

        role = channel.guild.get_role(
            role_id
        )

        if role:

            mentions.append(
                role.mention
            )


    mention_text = " ".join(
        mentions
    )


    # =========================
    # DUE DATE
    # =========================

    due = datetime.fromisoformat(
        homework["due_date"]
    )


    # =========================
    # MESSAGE
    # =========================

    message = (

        f"🔔 **HOMEWORK REMINDER**\n\n"

        f"{mention_text}\n\n"

        f"📚 **Subject:** "
        f"{homework['subject']}\n"

        f"📝 **Description:** "
        f"{homework['description']}\n"

        f"⏰ **Due:** "
        f"{due.strftime('%d/%m/%Y %H:%M')}\n\n"

        f"⚠️ Due in **{time_remaining}**."

    )


    # =========================
    # SEND
    # =========================

    await channel.send(

        message,

        allowed_mentions=discord.AllowedMentions(
            roles=True
        )

    )


# =========================
# RUN BOT
# =========================

if not TOKEN:

    print(
        "ERROR: DISCORD_TOKEN was not found "
        "in your .env file."
    )

else:

    bot.run(TOKEN)