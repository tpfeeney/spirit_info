import discord
from discord import app_commands
from discord.ext import commands
import json
import os
from difflib import get_close_matches
from dotenv import load_dotenv

load_dotenv()

OWNER_ID = int(os.getenv("OWNER_ID"))
DATA_DIR = "data"

CATEGORY_LABELS = {
    "rc": "Rare Character",
    "nbc": "New Brand/Bottled-in-Bond Codes",
}


def load_json(filename, default=None):
    """Load JSON file, return default if not found"""
    if default is None:
        default = {}
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        print(f"[WARN] Data file not found: {path}")
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"[ERROR] Invalid JSON in {filename}: {e}")
        return default


def build_brand_index(mashbills):
    """Build index of brands for fast lookup"""
    index = {}
    for mb_name, mb_data in mashbills.items():
        for brand in mb_data.get("brands", []):
            key = brand.lower().strip()
            index.setdefault(key, []).append(mb_name)
    return index


def chunk_by_length(items, prefix="• ", max_len=1024):
    """Chunk items into groups that fit within max_len when joined with newlines"""
    chunks = []
    current_chunk = []
    current_len = 0

    for item in items:
        line = f"{prefix}{item}"
        line_len = len(line) + 1  # +1 for newline

        if current_len + line_len > max_len and current_chunk:
            chunks.append(current_chunk)
            current_chunk = [line]
            current_len = line_len
        else:
            current_chunk.append(line)
            current_len += line_len

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def build_mashbill_embed(mb_name, mb_data):
    """Build a single embed for one mashbill and its brands, one per line"""
    grain_str = ", ".join(f"{k}: {v}" for k, v in mb_data.get("grains", {}).items()) if isinstance(mb_data.get("grains"), dict) else ", ".join(mb_data.get("grains", []))
    brands = mb_data.get("brands", [])

    embed = discord.Embed(
        title=f"🌾 {mb_name}",
        description=f"**Grains:** {grain_str}",
        color=discord.Color.gold(),
    )

    brand_chunks = chunk_by_length(brands)
    for idx, chunk in enumerate(brand_chunks):
        field_name = f"🥃 Brands ({len(brands)})" if idx == 0 else "🥃 Brands (cont.)"
        embed.add_field(
            name=field_name,
            value="\n".join(chunk),
            inline=False,
        )

    return embed


# Load all data at module import time
CATEGORIES = {
    "rc": load_json("rc_codes.json"),
    "nbc": load_json("nbc_codes.json"),
}
MASHBILLS = load_json("mashbills.json")
BRAND_INDEX = build_brand_index(MASHBILLS)


async def rc_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    """Autocomplete for RC codes"""
    current_lower = current.lower()
    cat_data = CATEGORIES.get("rc", {})
    return [
        app_commands.Choice(name=code, value=code)
        for code in sorted(cat_data.keys())
        if current_lower in code.lower()
    ][:25]


async def nbc_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    """Autocomplete for NBC codes"""
    current_lower = current.lower()
    cat_data = CATEGORIES.get("nbc", {})
    return [
        app_commands.Choice(name=code, value=code)
        for code in sorted(cat_data.keys())
        if current_lower in code.lower()
    ][:25]


async def mashbill_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    """Autocomplete for mashbills with fuzzy search"""
    current_lower = current.lower()
    matches = [
        name for name in MASHBILLS.keys()
        if current_lower in name.lower()
    ]
    return [
        app_commands.Choice(name=name, value=name)
        for name in sorted(matches)
    ][:25]


async def brand_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    """Autocomplete for brand names"""
    current_lower = current.lower()
    matches = [
        brand for brand in BRAND_INDEX.keys()
        if current_lower in brand.lower()
    ]
    return [
        app_commands.Choice(name=brand.title(), value=brand)
        for brand in sorted(matches)
    ][:25]


class LookupCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def build_entry_embed(self, cat_key, code, entry):
        """Build embed for a single entry - displays all fields"""
        label = CATEGORY_LABELS.get(cat_key, cat_key)
        embed = discord.Embed(
            title=f"🥃 {code}",
            description=f"**{entry.get('name', 'Unknown')}**\n*{label}*",
            color=discord.Color.dark_gold(),
        )

        priority_fields = ["mashbill", "source", "type", "distillery", "age", "proof", "finish"]

        for field_name in priority_fields:
            if field_name in entry and entry[field_name]:
                display_name = field_name.replace("_", " ").title()
                embed.add_field(name=display_name, value=entry[field_name], inline=True)

        for key, value in entry.items():
            if key not in priority_fields and key != "name" and value:
                display_name = key.replace("_", " ").title()
                inline = len(str(value)) < 50
                embed.add_field(name=display_name, value=value, inline=inline)

        return embed

    def not_found_message(self, code, cat_label=None):
        """Build not-found message"""
        msg = f"❌ Code `{code}` not found"
        if cat_label:
            msg += f" in {cat_label}"
        msg += "."
        return msg

    @app_commands.command(name="lookup", description="Look up codes, mashbills, or brands")
    @app_commands.describe(
        type="Choose what to look up",
        query="The code, mashbill, or brand name to search for"
    )
    @app_commands.choices(type=[
        app_commands.Choice(name="rc", value="rc"),
        app_commands.Choice(name="nbc", value="nbc"),
        app_commands.Choice(name="mashbill", value="mashbill"),
        app_commands.Choice(name="brand", value="brand")
    ])
    async def lookup(self, interaction: discord.Interaction, type: app_commands.Choice[str], query: str):
        """Unified lookup command"""
        lookup_type = type.value
        search_query = query.strip()

        if lookup_type == "rc":
            cat_data = CATEGORIES.get("rc", {})

            matched_key = None
            for key in cat_data.keys():
                if key.upper() == search_query.upper():
                    matched_key = key
                    break

            if matched_key:
                entry = cat_data[matched_key]
                embed = self.build_entry_embed("rc", matched_key, entry)
                await interaction.response.send_message(embed=embed)
                return

            close = get_close_matches(search_query.upper(), [k.upper() for k in cat_data.keys()], n=3, cutoff=0.5)
            msg = self.not_found_message(search_query, "Rare Character")
            if close:
                msg += f"\nDid you mean: {', '.join(close)}?"
            await interaction.response.send_message(msg, ephemeral=True)

        elif lookup_type == "nbc":
            cat_data = CATEGORIES.get("nbc", {})

            matched_key = None
            for key in cat_data.keys():
                if key.upper() == search_query.upper():
                    matched_key = key
                    break

            if matched_key:
                entry = cat_data[matched_key]
                embed = self.build_entry_embed("nbc", matched_key, entry)
                await interaction.response.send_message(embed=embed)
                return

            close = get_close_matches(search_query.upper(), [k.upper() for k in cat_data.keys()], n=3, cutoff=0.5)
            msg = self.not_found_message(search_query, "NBC Codes")
            if close:
                msg += f"\nDid you mean: {', '.join(close)}?"
            await interaction.response.send_message(msg, ephemeral=True)

        elif lookup_type == "mashbill":
            search_query_lower = search_query.lower()

            # 1. Try exact match first (user selected from autocomplete dropdown)
            matched_name = None
            for name in MASHBILLS.keys():
                if name.lower() == search_query_lower:
                    matched_name = name
                    break

            if matched_name:
                embed = build_mashbill_embed(matched_name, MASHBILLS[matched_name])
                await interaction.response.send_message(embed=embed)
                return

            # 2. No exact match - fuzzy substring search across all mashbill names
            matches = [
                name for name in MASHBILLS.keys()
                if search_query_lower in name.lower()
            ]

            if not matches:
                close = get_close_matches(search_query, list(MASHBILLS.keys()), n=3, cutoff=0.5)
                msg = f"❌ No mashbill found matching '{query}'"
                if close:
                    msg += f"\nDid you mean: {', '.join(close)}?"
                await interaction.response.send_message(msg, ephemeral=True)
                return

            if len(matches) == 1:
                # Only one match - show it directly, fully expanded
                matched_name = matches[0]
                embed = build_mashbill_embed(matched_name, MASHBILLS[matched_name])
                await interaction.response.send_message(embed=embed)
                return

            # 3. Multiple matches - show a pick-list so the user can narrow down
            embed = discord.Embed(
                title=f"🔍 Multiple mashbills match '{query}'",
                description="Select one from the autocomplete dropdown, or refine your search:",
                color=discord.Color.gold(),
            )
            embed.add_field(
                name="Matches",
                value="\n".join(f"• {name}" for name in matches[:25]),
                inline=False,
            )
            if len(matches) > 25:
                embed.set_footer(text=f"Showing 25 of {len(matches)} matches")
            await interaction.response.send_message(embed=embed, ephemeral=True)

        elif lookup_type == "brand":
            search_query_lower = search_query.lower()

            # Try exact match first (user selected from autocomplete)
            if search_query_lower in BRAND_INDEX:
                mashbill_names = BRAND_INDEX[search_query_lower]
                embed = discord.Embed(
                    title=f"🏷️ {search_query.title()}",
                    color=discord.Color.blue(),
                )
                embed.add_field(
                    name="Mashbills",
                    value="\n".join(f"• {name}" for name in mashbill_names),
                    inline=False,
                )
                await interaction.response.send_message(embed=embed)
                return

            # Fuzzy substring search
            matching_brands = [
                brand for brand in BRAND_INDEX.keys()
                if search_query_lower in brand.lower()
            ]

            if not matching_brands:
                close = get_close_matches(search_query_lower, list(BRAND_INDEX.keys()), n=3, cutoff=0.5)
                msg = f"❌ No brand found matching '{query}'"
                if close:
                    msg += f"\nDid you mean: {', '.join(c.title() for c in close)}?"
                await interaction.response.send_message(msg, ephemeral=True)
                return

            if len(matching_brands) == 1:
                brand = matching_brands[0]
                mashbill_names = BRAND_INDEX[brand]
                embed = discord.Embed(
                    title=f"🏷️ {brand.title()}",
                    color=discord.Color.blue(),
                )
                embed.add_field(
                    name="Mashbills",
                    value="\n".join(f"• {name}" for name in mashbill_names),
                    inline=False,
                )
                await interaction.response.send_message(embed=embed)
                return

            # Multiple brand matches - show pick-list
            embed = discord.Embed(
                title=f"🔍 Multiple brands match '{query}'",
                description="Select one from the autocomplete dropdown, or refine your search:",
                color=discord.Color.blue(),
            )
            embed.add_field(
                name="Matches",
                value="\n".join(f"• {b.title()}" for b in matching_brands[:25]),
                inline=False,
            )
            if len(matching_brands) > 25:
                embed.set_footer(text=f"Showing 25 of {len(matching_brands)} matches")
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @lookup.autocomplete("query")
    async def lookup_query_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        """Dynamic autocomplete based on the selected type"""
        type_value = None
        for option in interaction.data.get("options", []):
            if option["name"] == "type":
                type_value = option.get("value")
                break

        if type_value == "rc":
            return await rc_autocomplete(interaction, current)
        elif type_value == "nbc":
            return await nbc_autocomplete(interaction, current)
        elif type_value == "mashbill":
            return await mashbill_autocomplete(interaction, current)
        elif type_value == "brand":
            return await brand_autocomplete(interaction, current)

        return []

    @app_commands.command(name="reload-data", description="Reload data files (owner only)")
    async def reload_data(self, interaction: discord.Interaction):
        """Reload all data from JSON files"""
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message(
                "❌ You don't have permission to use this command.",
                ephemeral=True
            )
            return

        global CATEGORIES, MASHBILLS, BRAND_INDEX
        CATEGORIES = {
            "rc": load_json("rc_codes.json"),
            "nbc": load_json("nbc_codes.json"),
        }
        MASHBILLS = load_json("mashbills.json")
        BRAND_INDEX = build_brand_index(MASHBILLS)

        await interaction.response.send_message(
            "✅ Data reloaded successfully!", ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(LookupCog(bot))