#!/bin/python3
import json
import random
import asyncio
import datetime

import discord
from discord.ext import tasks, commands

from openai import OpenAI

# Constants
TZ = datetime.timezone.utc
TIME = datetime.time(hour=0, minute=0, second=0, tzinfo=TZ)

EMBED = json.load(open("embed.json"))
CONFIG = json.load(open("config.json"))
SECRETS = json.load(open("secrets.json"))

# OpenAI setup.
client = OpenAI(api_key=SECRETS["OpenAI"]["token"])
prompt_asst = CONFIG["OpenAI"]["p_assistant"]         # Assistant responsible for creative prompts
crit_asst = CONFIG["OpenAI"]["c_assistant"]           # Assistant responsible for grading

thread = None

# Discord.py setup.
intents = discord.Intents.default()
intents.message_content = True

bot = discord.Client(intents=intents)

# Variables to be reset daily.
m_id = 0                # Message ID assosciated with writing prompt.
users_responded = []    # Limit to one response a day; add user when they respond

async def _runAsst(a_id, t_id, content):
    """ Actually push messages using assistant passed by `a_id`
        on its respective thread's `t_id` and receive its response.
    """
    message = client.beta.threads.messages.create(
        thread_id = t_id,
        role = "user",
        content = content
    )

    run = client.beta.threads.runs.create(
        thread_id = t_id,
        assistant_id = a_id,
    )

    while run.status != "completed":
        run = client.beta.threads.runs.retrieve(thread_id=t_id, run_id=run.id)
        print(f"{run.status}")
        await asyncio.sleep(0.5)

    message_response = client.beta.threads.messages.list(thread_id=t_id)
    messages = message_response.data

    latest_message = messages[0]
    return latest_message.content[0].text.value
 
@tasks.loop(time=TIME)
async def writing_daily():
    """ Once a day, at 00:00 UTC-0:
        - Randomly select hyperparameters (i.e., genre, age group,
          tragedy/comedy).
        - Forward them to GPT for a creative writing prompt.
    """
    global users_responded, thread, m_id
    users_responded = []    # Reset record.

    genre = random.choice(CONFIG["OpenAI"]["genres"])
    age_group = random.choice(CONFIG["OpenAI"]["ages"])
    tragcmdy = random.choice(["Tragedy", "Comedy"])

    # Re-create thread to combat limited context window.
    thread = client.beta.threads.create()

    response = (await _runAsst(
        prompt_asst, thread.id, 
        f"{ genre }, { age_group }, { tragcmdy }")
    )

    channel = bot.get_channel(CONFIG["Discord"]["channel"])

    # Set up discord embed.
    prompt_embed = EMBED["prompt"]
    prompt_embed["description"] = response
    prompt_embed["fields"][0]["value"] = genre
    prompt_embed["fields"][1]["value"] = age_group
    prompt_embed["fields"][2]["value"] = tragcmdy

    # Save the message id of the prompt to check against in `on_message`.
    m_id = (await channel.send(embed=discord.Embed.from_dict(prompt_embed))).id

@bot.event
async def on_message(message):
    if message.author != bot.user and message.reference:
        print(message.author.id)
        if message.reference.message_id == m_id and message.author.id not in users_responded:
            users_responded.append(message.author.id)

            grade = (await _runAsst(
                        crit_asst, thread.id, message.content, 
                    ))
            grade_embed = EMBED["response"]
            grade_embed["description"] = grade
            grade_embed["thumbnail"]["url"] = message.author.avatar.url

            await message.reply(embed=discord.Embed.from_dict(grade_embed))

@bot.event
async def on_ready():
    if not writing_daily.is_running():
        writing_daily.start()

    print(f"Logged on as { bot.user }!")

if __name__ == "__main__":
    bot.run(SECRETS["Discord"]["token"])
