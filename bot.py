import os
import dotenv
dotenv.load_dotenv()

import discord
from discord.ext import commands
from config import DISCORD_TOKEN

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="/", intents=intents)


@bot.event
async def setup_hook():
    await bot.load_extension("cogs.lookup")
    await bot.load_extension("cogs.suggest")
    await bot.tree.sync()


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")


bot.run(DISCORD_TOKEN)
