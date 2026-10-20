"""
/suggest - lets anyone send the bot owner a suggestion.

This cog only ever SENDS A MESSAGE. It does not save suggestions, and it has
no command that changes the data files. To act on a suggestion, the owner
edits the JSON files in data/ by hand and runs /reload-data.
"""

import os
import re
import json
from typing import Optional

import discord
from discord import app_commands, ui
from discord.ext import commands

# ==================== CONFIG ====================
# Resolved relative to this file (cogs/suggest.py -> ../data), read-only use.
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


def _int_env(name: str) -> int:
    value = (os.getenv(name) or "").strip()
    try:
        return int(value) if value else 0
    except ValueError:
        print(f"[suggest] {name} is not a number; ignoring it")
        return 0


OWNER_ID = _int_env("OWNER_ID")
REVIEW_CHANNEL_ID = _int_env("REVIEW_CHANNEL_ID")  # optional: also post suggestions here

# How many times one person can open the suggestion form: 3 per 5 minutes
COOLDOWN_USES = 3
COOLDOWN_SECONDS = 300

NO_PINGS = discord.AllowedMentions.none()


# ==================== HELPERS ====================
def clean(text: str) -> str:
    """User text, made safe to show inside an embed (no formatting tricks)."""
    return discord.utils.escape_markdown((text or "").strip())


def load_mashbill_names() -> Optional[set]:
    """Names of the existing mashbills, or None if the file can't be read."""
    path = os.path.join(DATA_DIR, "mashbills.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    return set(data) if isinstance(data, dict) else None


async def send_suggestion(interaction: discord.Interaction, kind: str, fields: list):
    """
    Send a suggestion to the owner by DM (and to the review channel, if one is
    set), then tell the submitter whether it got through.

    `fields` is a list of (label, value) pairs; empty values are skipped.
    """
    # Sending a DM can take longer than Discord's 3-second reply window
    await interaction.response.defer(ephemeral=True, thinking=True)

    lines = [f"**{label}:** {clean(value)}" for label, value in fields if value and value.strip()]
    body = "\n".join(lines)

    user = interaction.user
    where = f"#{interaction.channel}" if interaction.guild else "a direct message"
    if interaction.guild:
        where += f" in {interaction.guild.name}"

    owner_embed = discord.Embed(
        title=f"🔔 Suggestion: {kind}",
        description=body,
        color=discord.Color.gold(),
    )
    owner_embed.add_field(
        name="From",
        value=f"{user.mention} ({clean(str(user))}, ID {user.id})\nSent from {clean(where)}"[:1024],
        inline=False,
    )

    delivered = False

    if OWNER_ID:
        try:
            client = interaction.client
            owner = client.get_user(OWNER_ID) or await client.fetch_user(OWNER_ID)
            await owner.send(embed=owner_embed, allowed_mentions=NO_PINGS)
            delivered = True
        except discord.Forbidden:
            print("[suggest] Could not DM the owner - they may have DMs from the bot disabled.")
        except discord.HTTPException as e:
            print(f"[suggest] Error DMing owner: {e}")
    else:
        print("[suggest] OWNER_ID is not set, so there is nobody to DM.")

    if REVIEW_CHANNEL_ID:
        channel = interaction.client.get_channel(REVIEW_CHANNEL_ID)
        if channel is not None:
            try:
                await channel.send(embed=owner_embed, allowed_mentions=NO_PINGS)
                delivered = True
            except discord.HTTPException as e:
                print(f"[suggest] Error sending to review channel: {e}")

    if not delivered:
        await interaction.followup.send(
            "❌ Sorry, your suggestion couldn't be delivered right now. Please try again later.",
            ephemeral=True,
        )
        return

    receipt = discord.Embed(
        title="📝 Suggestion sent",
        description=f"**Type:** {kind}\n{body}",
        color=discord.Color.blue(),
    )
    receipt.set_footer(text="The bot owner reviews suggestions by hand, so changes aren't instant.")
    await interaction.followup.send(embed=receipt, ephemeral=True)


# ==================== FORMS ====================
class NewMashbillModal(ui.Modal, title="Suggest a New Mashbill"):
    mashbill = ui.TextInput(
        label="Mashbill",
        placeholder="e.g., 51C/25R/24MB",
        required=True,
        max_length=50,
    )
    brand_name = ui.TextInput(
        label="Brand Name (Optional)",
        placeholder="Enter brand/product name",
        required=False,
        max_length=100,
    )

    async def on_submit(self, interaction: discord.Interaction):
        existing = load_mashbill_names()
        if existing is not None and self.mashbill.value.strip() in existing:
            await interaction.response.send_message(
                f"❌ Mashbill `{clean(self.mashbill.value)}` already exists!",
                ephemeral=True,
            )
            return

        await send_suggestion(interaction, "New Mashbill", [
            ("Mashbill", self.mashbill.value),
            ("Brand", self.brand_name.value),
        ])


class BrandToMashbillModal(ui.Modal, title="Suggest a Brand for a Mashbill"):
    mashbill = ui.TextInput(
        label="Mashbill",
        placeholder="e.g., 75C/21R/4MB",
        required=True,
        max_length=50,
    )
    brand_name = ui.TextInput(
        label="Brand Name",
        placeholder="Enter brand/product name",
        required=True,
        max_length=100,
    )

    async def on_submit(self, interaction: discord.Interaction):
        existing = load_mashbill_names()
        if existing is not None and self.mashbill.value.strip() not in existing:
            await interaction.response.send_message(
                f"❌ Mashbill `{clean(self.mashbill.value)}` not found. Please check the spelling.",
                ephemeral=True,
            )
            return

        await send_suggestion(interaction, "Brand to Existing Mashbill", [
            ("Mashbill", self.mashbill.value),
            ("Brand", self.brand_name.value),
        ])


class NewRCCodeModal(ui.Modal, title="Suggest a New RC Code"):
    code = ui.TextInput(label="Code", placeholder="e.g., RIO", required=True, max_length=20)
    rc_type = ui.TextInput(
        label="Type (Optional)", placeholder="e.g., Bourbon, Rye", required=False, max_length=50
    )
    mashbill = ui.TextInput(
        label="Mashbill (Optional)", placeholder="e.g., 75/21/4", required=False, max_length=50
    )
    source = ui.TextInput(
        label="Source (Optional)", placeholder="e.g., MGP, Barton", required=False, max_length=100
    )
    aging_location = ui.TextInput(
        label="Aging Location (Optional)", placeholder="e.g., KY, IN, TN", required=False, max_length=100
    )

    async def on_submit(self, interaction: discord.Interaction):
        await send_suggestion(interaction, "New RC Code", [
            ("Code", self.code.value),
            ("Type", self.rc_type.value),
            ("Mashbill", self.mashbill.value),
            ("Source", self.source.value),
            ("Aging Location", self.aging_location.value),
        ])


class NewNBCCodeModal(ui.Modal, title="Suggest a New NBC Code"):
    code = ui.TextInput(label="Code", placeholder="e.g., 52xx format", required=True, max_length=20)
    source = ui.TextInput(
        label="Source (Optional)", placeholder="e.g., MGP, Barton", required=False, max_length=100
    )
    mashbill = ui.TextInput(
        label="Mashbill (Optional)", placeholder="e.g., 75/21/4", required=False, max_length=50
    )
    barrel = ui.TextInput(
        label="Barrel (Optional)", placeholder="e.g., Kelvin, ISC", required=False, max_length=100
    )
    note = ui.TextInput(
        label="Note (Optional)",
        placeholder="Additional notes",
        required=False,
        max_length=200,
        style=discord.TextStyle.paragraph,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await send_suggestion(interaction, "New NBC Code", [
            ("Code", self.code.value),
            ("Source", self.source.value),
            ("Mashbill", self.mashbill.value),
            ("Barrel", self.barrel.value),
            ("Note", self.note.value),
        ])


class UpdateRCCodeModal(ui.Modal, title="Suggest an RC Code Correction"):
    code = ui.TextInput(label="Code to Update", placeholder="e.g., RIO", required=True, max_length=20)
    field = ui.TextInput(
        label="Field to Update",
        placeholder="e.g., type, mashbill, source, aging_location",
        required=True,
        max_length=50,
    )
    value = ui.TextInput(label="New Value", placeholder="Enter new value", required=True, max_length=200)

    async def on_submit(self, interaction: discord.Interaction):
        await send_suggestion(interaction, "Update RC Code", [
            ("Code", self.code.value),
            ("Field", self.field.value),
            ("New Value", self.value.value),
        ])


class UpdateNBCCodeModal(ui.Modal, title="Suggest an NBC Code Correction"):
    code = ui.TextInput(label="Code to Update", placeholder="e.g., 52xx", required=True, max_length=20)
    field = ui.TextInput(
        label="Field to Update",
        placeholder="e.g., source, mashbill, barrel, note",
        required=True,
        max_length=50,
    )
    value = ui.TextInput(label="New Value", placeholder="Enter new value", required=True, max_length=200)

    async def on_submit(self, interaction: discord.Interaction):
        await send_suggestion(interaction, "Update NBC Code", [
            ("Code", self.code.value),
            ("Field", self.field.value),
            ("New Value", self.value.value),
        ])


class NewBangCommandModal(ui.Modal, title="Suggest a ! Command"):
    suggestion = ui.TextInput(
        label="Command Suggestion",
        placeholder="e.g., !barrelproof - look up barrel proof for a given code",
        required=True,
        max_length=1000,
        style=discord.TextStyle.paragraph,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await send_suggestion(interaction, "New ! Command", [
            ("Suggestion", self.suggestion.value),
        ])


DSP_NUMBER_RE = re.compile(r"\bD\.?\s*S\.?\s*P\.?[\s\-#:.]*([A-Z]{2})[\s\-#:.]*(\d{1,6})\b", re.IGNORECASE)


class NewDSPNumberModal(ui.Modal, title="Suggest a DSP Number"):
    number = ui.TextInput(label="DSP Number", placeholder="e.g., DSP-KY-113", required=True, max_length=30)
    distillery = ui.TextInput(
        label="Distillery", placeholder="e.g., Buffalo Trace Distillery", required=True, max_length=100
    )
    location = ui.TextInput(label="City, State (Optional)", placeholder="e.g., Frankfort, KY", required=False, max_length=100)
    evidence = ui.TextInput(
        label="Where you saw it (Optional)",
        placeholder="e.g., back label of a BiB bottle, or a link to a photo",
        required=False,
        max_length=300,
        style=discord.TextStyle.paragraph,
    )

    async def on_submit(self, interaction: discord.Interaction):
        m = DSP_NUMBER_RE.search(self.number.value) or re.match(
            r"^\s*([A-Z]{2})[\s\-#:.]*(\d{1,6})\s*$", self.number.value, re.IGNORECASE
        )
        if not m:
            await interaction.response.send_message(
                f"❌ `{clean(self.number.value)}` doesn't look like a DSP number. Use a format like DSP-KY-113.",
                ephemeral=True,
            )
            return
        number = f"DSP-{m.group(1).upper()}-{int(m.group(2))}"
        await send_suggestion(interaction, "DSP Number", [
            ("DSP Number", number),
            ("Distillery", self.distillery.value),
            ("Location", self.location.value),
            ("Seen on", self.evidence.value),
        ])


MODALS = {
    "brand_to_mashbill": BrandToMashbillModal,
    "new_mashbill": NewMashbillModal,
    "new_rc_code": NewRCCodeModal,
    "update_rc_code": UpdateRCCodeModal,
    "new_nbc_code": NewNBCCodeModal,
    "update_nbc_code": UpdateNBCCodeModal,
    "new_bang_command": NewBangCommandModal,
    "new_dsp_number": NewDSPNumberModal,
}


# ==================== COG ====================
class SuggestCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="suggest", description="Send a suggestion to the bot owner")
    @app_commands.describe(action="What would you like to suggest?")
    @app_commands.choices(action=[
        app_commands.Choice(name="Brand to Existing Mashbill", value="brand_to_mashbill"),
        app_commands.Choice(name="New Mashbill", value="new_mashbill"),
        app_commands.Choice(name="New RC Code", value="new_rc_code"),
        app_commands.Choice(name="Update RC Code", value="update_rc_code"),
        app_commands.Choice(name="New NBC Code", value="new_nbc_code"),
        app_commands.Choice(name="Update NBC Code", value="update_nbc_code"),
        app_commands.Choice(name="Add ! Command", value="new_bang_command"),
        app_commands.Choice(name="DSP Number", value="new_dsp_number"),
    ])
    @app_commands.checks.cooldown(COOLDOWN_USES, COOLDOWN_SECONDS, key=lambda i: i.user.id)
    async def suggest(self, interaction: discord.Interaction, action: str):
        modal_class = MODALS.get(action)
        if modal_class is None:
            await interaction.response.send_message("❌ Unknown suggestion type.", ephemeral=True)
            return
        await interaction.response.send_modal(modal_class())

    @suggest.error
    async def suggest_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CommandOnCooldown):
            minutes = max(1, round(error.retry_after / 60))
            await interaction.response.send_message(
                f"⏳ You're sending suggestions quickly. Please try again in about {minutes} minute(s).",
                ephemeral=True,
            )
            return
        # Anything else is logged by discord.py's default error handler


async def setup(bot):
    """Load the suggest cog."""
    await bot.add_cog(SuggestCog(bot))
