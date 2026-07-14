import os
import dotenv
dotenv.load_dotenv()

import discord
from discord.ext import commands
from config import DISCORD_TOKEN

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="/", intents=intents)


async def load_extensions():
    await bot.load_extension("cogs.lookup")
    await bot.load_extension("cogs.suggest")


@bot.event
async def setup_hook():
    # Fire once before on_ready — load extensions here
    await load_extensions()


@bot.event
async def on_ready():
    # Extensions are already loaded; now sync slash commands
    await bot.tree.sync()
    print(f"Logged in as {bot.user}")
    print("Slash commands synced!")


bot.run(DISCORD_TOKEN)