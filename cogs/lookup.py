import os
import json
import difflib
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands

from config import OWNER_ID, REVIEW_CHANNEL_ID, DATA_DIR, SUGGESTIONS_FILE

CATEGORIES: dict[str, dict] = {}
_suggestion_counter = 0


def load_data():
    global CATEGORIES
    CATEGORIES = {}
    data_dir = DATA_DIR.lstrip("./")
    for filename in os.listdir(data_dir):
        if filename.endswith(".json"):
            category = filename.replace(".json", "")
            path = os.path.join(data_dir, filename)
            with open(path) as f:
                CATEGORIES[category] = json.load(f)


load_data()


class LookupCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="lookup", description="Look up spirit codes, mashbills, and NBC barrels")
    @app_commands.describe(code="The spirit code, mashbill code, or NBC barrel ID")
    async def lookup(self, interaction: discord.Interaction, code: str):
        code_upper = code.strip().upper()
        results = {}

        for category, entries in CATEGORIES.items():
            for key, entry in entries.items():
                if key.upper() == code_upper or entry.get("name", "").upper() == code_upper:
                    results[key] = (category, entry)
                    break

        if not results:
            suggestions = []
            for category, entries in CATEGORIES.items():
                for key in entries:
                    ratio = difflib.get_close_matches(code_upper, [key.upper()], 1, 0.6)
                    if ratio:
                        suggestions.append(key)
            close = difflib.get_close_matches(
                code_upper,
                [k.upper() for k in sum((list(v.keys()) for v in CATEGORIES.values()), [])],
                n=3,
                cutoff=0.5,
            )
            if close:
                await interaction.response.send_message(
                    f'No match for "{code_upper}". Did you mean: {", ".join(close)}?',
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    f'No match for "{code_upper}". No close matches found.',
                    ephemeral=True,
                )
            return

        for key, (category, entry) in results.items():
            fields = [
                {"name": "Code", "value": key, "inline": True},
                {"name": "Category", "value": category, "inline": True},
            ]
            if entry.get("name"):
                fields.append({"name": "Name", "value": entry["name"], "inline": True})
            if entry.get("mashbill"):
                fields.append({"name": "Mashbill", "value": entry["mashbill"], "inline": False})
            if entry.get("source"):
                fields.append({"name": "Source", "value": entry["source"], "inline": False})
            if entry.get("notes"):
                fields.append({"name": "Notes", "value": entry["notes"], "inline": False})

            if len(entry) <= 1:
                embed = discord.Embed(
                    title=f"🔶 {key}",
                    color=discord.Color.orange(),
                )
                embed.add_field(name="Name", value=entry.get("name", key), inline=False)
                embed.add_field(
                    name="Details",
                    value=f"This entry exists in **{category}** but is still being researched. "
                    f"Want to help? Reach out to <@{OWNER_ID}>!",
                    inline=False,
                )
            else:
                embed = discord.Embed(
                    title=f"🥇 {key}",
                    color=discord.Color.gold(),
                )
                for field in fields:
                    embed.add_field(**field)

            embed.set_footer(text=f"Category: {category}")
            await interaction.response.send_message(embed=embed)

    @lookup.autocomplete("code")
    async def code_autocomplete(self, interaction: discord.Interaction, current: str):
        global _suggestion_counter
        _suggestion_counter += 1
        all_codes = []
        for category, entries in CATEGORIES.items():
            for key in entries:
                all_codes.append(key)
        matches = difflib.get_close_matches(current.upper(), all_codes, n=5, cutoff=0.4)
        return [
            app_commands.Choice(name=code, value=code)
            for code in (matches if matches else all_codes[:5])
        ]

    @app_commands.command(name="reload", description="Reload data files (owner only)")
    async def reload(self, interaction: discord.Interaction):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("❌ Not authorized.", ephemeral=True)
            return
        load_data()
        total = sum(len(v) for v in CATEGORIES.values())
        await interaction.response.send_message(
            f"🔄 Reloaded {len(CATEGORIES)} categories, {total} entries.", ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(LookupCog(bot))
