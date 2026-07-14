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
        
        # Define field order priority (these appear first if they exist)
        priority_fields = ["mashbill", "source", "type", "distillery", "age", "proof", "finish"]
        
        # Add priority fields first
        for field_name in priority_fields:
            if field_name in entry and entry[field_name]:
                display_name = field_name.replace("_", " ").title()
                embed.add_field(name=display_name, value=entry[field_name], inline=True)
        
        # Add all other fields (except 'name' which is in description)
        for key, value in entry.items():
            if key not in priority_fields and key != "name" and value:
                display_name = key.replace("_", " ").title()
                # Use inline=False for longer text fields
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
            # Case insensitive search for RC codes
            cat_data = CATEGORIES.get("rc", {})
            
            # Try to find case-insensitive match
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
            # Case insensitive search for NBC codes
            cat_data = CATEGORIES.get("nbc", {})
            
            # Try to find case-insensitive match
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
            # Fuzzy search for mashbills - find any mashbill containing the query
            search_query_lower = search_query.lower()
            matches = [
                name for name in MASHBILLS.keys()
                if search_query_lower in name.lower()
            ]
            
            if not matches:
                await interaction.response.send_message(
                    f"❌ No mashbill found matching '{query}'",
                    ephemeral=True
                )
                return
            
            embed = discord.Embed(
                title=f"🥃 Mashbill matches for '{query}'",
                color=discord.Color.gold(),
            )
            
            for mb_name in matches[:10]:
                mb_data = MASHBILLS[mb_name]
                grain_str = ", ".join(mb_data.get("grains", []))
                brands = mb_data.get("brands", [])
                brands_str = ", ".join(brands[:5])
                if len(brands) > 5:
                    brands_str += f" (+{len(brands)-5} more)"
                
                embed.add_field(
                    name=f"🌾 {mb_name}",
                    value=f"**Grains:** {grain_str}\n**Brands ({len(brands)}):** {brands_str}",
                    inline=False,
                )
            
            if len(matches) > 10:
                embed.set_footer(text=f"Showing 10 of {len(matches)} matches")
            await interaction.response.send_message(embed=embed)
        
        elif lookup_type == "brand":
            # Reverse lookup - find mashbills by brand name
            search_query_lower = search_query.lower()
            
            # Find all brands that match (fuzzy)
            matching_brands = [
                brand for brand in BRAND_INDEX.keys()
                if search_query_lower in brand.lower()
            ]
            
            if not matching_brands:
                await interaction.response.send_message(
                    f"❌ No brand found matching '{query}'",
                    ephemeral=True
                )
                return
            
            embed = discord.Embed(
                title=f"🏷️ Brand search results for '{query}'",
                color=discord.Color.blue(),
            )
            
            # Show results for each matching brand
            for brand in matching_brands[:5]:  # Limit to 5 brands
                mashbill_names = BRAND_INDEX[brand]
                mashbills_str = ", ".join(mashbill_names)
                
                embed.add_field(
                    name=f"🥃 {brand.title()}",
                    value=f"**Mashbills:** {mashbills_str}",
                    inline=False,
                )
            
            if len(matching_brands) > 5:
                embed.set_footer(text=f"Showing 5 of {len(matching_brands)} brand matches")
            
            await interaction.response.send_message(embed=embed)

    # Dynamic autocomplete based on type selection
    @lookup.autocomplete("query")
    async def lookup_query_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        """Dynamic autocomplete based on the selected type"""
        # Get the current value of the 'type' parameter
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
        
        # Default: return empty list
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