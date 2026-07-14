import os
import json
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands

from config import OWNER_ID, REVIEW_CHANNEL_ID, DATA_DIR, SUGGESTIONS_FILE

CATEGORIES = []
_suggestion_counter = 0


def get_categories():
    global CATEGORIES
    if not CATEGORIES:
        data_dir = DATA_DIR.lstrip("./")
        if os.path.isdir(data_dir):
            CATEGORIES = [
                f.replace(".json", "") for f in os.listdir(data_dir) if f.endswith(".json")
            ]
    return CATEGORIES


def next_id():
    global _suggestion_counter
    _suggestion_counter += 1
    return _suggestion_counter


class SuggestCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="suggest", description="Submit a new spirit entry for review")
    @app_commands.describe(
        category="The data category (e.g. rare_character, mashbills, nbc)",
        code="The unique code for this entry",
        name="Display name for the entry",
        mashbill="Mashbill details (e.g. '60% corn, 36% rye, 4% barley')",
        source="Source or distillery name",
        notes="Additional notes or comments",
    )
    async def suggest(
        self,
        interaction: discord.Interaction,
        category: str,
        code: str,
        name: str,
        mashbill: str = None,
        source: str = None,
        notes: str = None,
    ):
        global _suggestion_counter
        if _suggestion_counter == 0:
            with open(SUGGESTIONS_FILE) as f:
                existing = json.load(f)
            if existing:
                _suggestion_counter = max(int(s.get("id", 0)) for s in existing)

        suggestion = {
            "id": next_id(),
            "category": category,
            "code": code,
            "name": name,
            "timestamp": datetime.utcnow().isoformat(),
            "submitted_by": str(interaction.user.id),
        }
        if mashbill:
            suggestion["mashbill"] = mashbill
        if source:
            suggestion["source"] = source
        if notes:
            suggestion["notes"] = notes

        with open(SUGGESTIONS_FILE) as f:
            queue = json.load(f)
        queue.append(suggestion)
        with open(SUGGESTIONS_FILE, "w") as f:
            json.dump(queue, f, indent=2)

        embed = discord.Embed(
            title="📝 New Suggestion Submitted",
            color=discord.Color.blue(),
            description=f"**ID:** `{suggestion['id']}`\n**Category:** `{category}`\n**Code:** `{code}`\n**Name:** `{name}`",
        )
        if mashbill:
            embed.add_field(name="Mashbill", value=mashbill, inline=False)
        if source:
            embed.add_field(name="Source", value=source, inline=False)
        if notes:
            embed.add_field(name="Notes", value=notes, inline=False)
        embed.set_footer(text=f"Submitted by {interaction.user} • Use /approve {suggestion['id']} to add it")

        if REVIEW_CHANNEL_ID:
            channel = self.bot.get_channel(REVIEW_CHANNEL_ID)
            if channel:
                await channel.send(embed=embed)

        await interaction.response.send_message(
            f"✅ Suggestion `{suggestion['id']}` submitted and queued for review!", ephemeral=True
        )

    @suggest.autocomplete("category")
    async def category_autocomplete(self, interaction: discord.Interaction, current: str):
        cats = get_categories()
        return [
            app_commands.Choice(name=cat, value=cat)
            for cat in cats if current.lower() in cat.lower()
        ][:25]

    @app_commands.command(name="suggestions", description="List all pending suggestions (owner only)")
    async def suggestions(self, interaction: discord.Interaction):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("❌ Not authorized.", ephemeral=True)
            return

        with open(SUGGESTIONS_FILE) as f:
            queue = json.load(f)

        if not queue:
            await interaction.response.send_message("📭 No pending suggestions.", ephemeral=True)
            return

        lines = []
        for s in queue:
            extra = ""
            if s.get("mashbill"):
                extra += f" | mashbill: {s['mashbill']}"
            if s.get("source"):
                extra += f" | source: {s['source']}"
            lines.append(f"`[{s['id']}]` **{s['category']}** / `{s['code']}` — {s['name']}{extra}")

        await interaction.response.send_message(
            "📋 **Pending Suggestions:**\n" + "\n".join(lines), ephemeral=True
        )

    @app_commands.command(name="approve", description="Approve and add a suggestion to the data (owner only)")
    @app_commands.describe(suggestion_id="The suggestion ID to approve")
    async def approve(self, interaction: discord.Interaction, suggestion_id: int):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("❌ Not authorized.", ephemeral=True)
            return

        with open(SUGGESTIONS_FILE) as f:
            queue = json.load(f)

        target = None
        for s in queue:
            if s["id"] == suggestion_id:
                target = s
                break

        if not target:
            await interaction.response.send_message(
                f"❌ Suggestion `{suggestion_id}` not found in queue.", ephemeral=True
            )
            return

        queue = [s for s in queue if s["id"] != suggestion_id]
        with open(SUGGESTIONS_FILE, "w") as f:
            json.dump(queue, f, indent=2)

        data_file = os.path.join(DATA_DIR.lstrip("./"), f"{target['category']}.json")
        data = {}
        if os.path.exists(data_file):
            with open(data_file) as f:
                data = json.load(f)

        entry = {"name": target["name"]}
        for field in ("mashbill", "source", "notes"):
            if target.get(field):
                entry[field] = target[field]

        data[target["code"]] = entry
        with open(data_file, "w") as f:
            json.dump(data, f, indent=2)

        await interaction.response.send_message(
            f"✅ Approved and added `{target['code']}` to **{target['category']}**.\n"
            "Use `/reload` to reload the bot's data.",
            ephemeral=True,
        )

        if REVIEW_CHANNEL_ID:
            channel = self.bot.get_channel(REVIEW_CHANNEL_ID)
            if channel:
                await channel.send(
                    f"✅ Suggestion `{suggestion_id}` has been approved by <@{OWNER_ID}>!"
                )

    @app_commands.command(name="reject", description="Reject a suggestion (owner only)")
    @app_commands.describe(suggestion_id="The suggestion ID to reject")
    async def reject(self, interaction: discord.Interaction, suggestion_id: int):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("❌ Not authorized.", ephemeral=True)
            return

        with open(SUGGESTIONS_FILE) as f:
            queue = json.load(f)

        if not any(s["id"] == suggestion_id for s in queue):
            await interaction.response.send_message(
                f"❌ Suggestion `{suggestion_id}` not found in queue.", ephemeral=True
            )
            return

        queue = [s for s in queue if s["id"] != suggestion_id]
        with open(SUGGESTIONS_FILE, "w") as f:
            json.dump(queue, f, indent=2)

        await interaction.response.send_message(
            f"❌ Rejected suggestion `{suggestion_id}`.", ephemeral=True
        )

        if REVIEW_CHANNEL_ID:
            channel = self.bot.get_channel(REVIEW_CHANNEL_ID)
            if channel:
                await channel.send(f"❌ Suggestion `{suggestion_id}` was rejected by <@{OWNER_ID}>.")


async def setup(bot):
    await bot.add_cog(SuggestCog(bot))
