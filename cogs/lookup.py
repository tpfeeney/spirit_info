import discord
from discord import app_commands
from discord.ext import commands
import json
import os
from difflib import get_close_matches
from dotenv import load_dotenv

load_dotenv()

OWNER_ID = int(os.getenv("OWNER_ID") or 0)

# Resolve the data folder relative to this file (cogs/lookup.py -> ../data),
# so it works no matter what working directory the host starts the bot from.
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

# Problems hit during the most recent load, so /reload-data can report them
LOAD_ERRORS = {}  # filename -> error message

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
        msg = f"{filename}: file not found at {path}"
        print(f"[WARN] {msg}")
        LOAD_ERRORS[filename] = msg
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        msg = f"{filename}: invalid JSON at line {e.lineno}, column {e.colno} ({e.msg})"
        print(f"[ERROR] {msg}")
        LOAD_ERRORS[filename] = msg
        return default
    if not isinstance(data, dict):
        msg = f"{filename}: expected a JSON object at the top level, got {type(data).__name__}"
        print(f"[ERROR] {msg}")
        LOAD_ERRORS[filename] = msg
        return default
    return data


def load_all():
    """Load every data file. Returns (categories, mashbills, brand_index, variant_parent)."""
    LOAD_ERRORS.clear()
    categories = {
        "rc": load_json("rc_codes.json"),
        "nbc": load_json("nbc_codes.json"),
    }
    mashbills = load_json("mashbills.json")
    print(
        f"[lookup] Loaded {len(categories['rc'])} RC codes, {len(categories['nbc'])} NBC codes, "
        f"{len(mashbills)} mashbills from {DATA_DIR}"
    )
    brand_index, variant_parent = build_brand_index(mashbills)
    return categories, mashbills, brand_index, variant_parent


# Original capitalization for each brand key. str.title() mangles names like
# "Booker's" into "Booker'S", so show names exactly as they're written in the data.
BRAND_DISPLAY = {}


def display_brand(key):
    return BRAND_DISPLAY.get(key) or key.title()


def build_brand_index(mashbills):
    """
    Build index of brands for fast lookup.

    Also indexes the original bottle names stored under each mashbill's
    "variants" (e.g. 'Booker's 2015-02 "Dot's Batch"'), so searching an old
    bottle name still finds its mashbill. variant_parent maps each of those
    names to the simplified brand it's listed under: {variant_key: [(mashbill, brand)]}.
    """
    index = {}
    variant_parent = {}
    BRAND_DISPLAY.clear()
    for mb_name, mb_data in mashbills.items():
        if not isinstance(mb_data, dict):
            continue
        for brand in mb_data.get("brands", []):
            key = str(brand).lower().strip()
            if key:
                index.setdefault(key, []).append(mb_name)
                BRAND_DISPLAY.setdefault(key, str(brand).strip())
        variants = mb_data.get("variants") or {}
        if not isinstance(variants, dict):
            continue
        for brand, names in variants.items():
            for name in names or []:
                key = str(name).lower().strip()
                if not key or key == str(brand).lower().strip():
                    continue
                if mb_name not in index.setdefault(key, []):
                    index[key].append(mb_name)
                BRAND_DISPLAY.setdefault(key, str(name).strip())
                variant_parent.setdefault(key, []).append((mb_name, brand))
    return index, variant_parent


def get_variants(mb_data):
    """Return the mashbill's {brand: [original bottle names]} dict (empty if none)."""
    variants = mb_data.get("variants") if isinstance(mb_data, dict) else None
    return variants if isinstance(variants, dict) else {}


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
    grains = mb_data.get("grains") or {}
    if isinstance(grains, dict):
        grain_str = ", ".join(f"{k.replace('_', ' ')}: {v}" for k, v in grains.items())
    else:
        grain_str = ", ".join(str(g) for g in grains)
    grain_str = grain_str or "Unknown"
    brands = mb_data.get("brands", [])
    variants = get_variants(mb_data)
    # "Booker's (14)" tells people there are individual bottles behind the button
    shown = [
        f"{b} ({len(variants[b])})" if len(variants.get(b) or []) > 1 else b
        for b in brands
    ]

    embed = discord.Embed(
        title=f"🌾 {mb_name}",
        description=f"**Grains:** {grain_str}",
        color=discord.Color.gold(),
    )

    brand_chunks = chunk_by_length(shown)
    for idx, chunk in enumerate(brand_chunks):
        field_name = f"🥃 Brands ({len(brands)})" if idx == 0 else "🥃 Brands (cont.)"
        embed.add_field(
            name=field_name,
            value="\n".join(chunk),
            inline=False,
        )

    return embed


# ---------- "Show individual bottles" button ----------
# The button's custom_id carries what to show, and clicks are handled by the
# on_interaction listener in LookupCog. Nothing is kept in memory, so buttons
# on old messages keep working after the bot restarts or reloads data.
MASHBILL_BUTTON_PREFIX = "mbvar:"   # mbvar:<mashbill name>
BRAND_BUTTON_PREFIX = "bvar:"       # bvar:<brand key>
CUSTOM_ID_MAX = 100                 # Discord limit
EMBED_CHAR_BUDGET = 5500            # Discord caps an embed at 6000 characters
EMBED_FIELD_LIMIT = 25


def make_bottles_view(custom_id, count):
    """A view with one 'Show individual bottles' button, or None if it can't be built."""
    if not count or len(custom_id) > CUSTOM_ID_MAX:
        return None
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(
        label=f"Show individual bottles ({count})",
        emoji="🍾",
        style=discord.ButtonStyle.secondary,
        custom_id=custom_id,
    ))
    # Stop the view so discord.py doesn't hold it in memory; the listener handles clicks.
    view.stop()
    return view


def build_bottle_embeds(title, groups):
    """
    Turn [(brand, [bottle names]), ...] into as many embeds as needed to stay
    within Discord's limits (1024 per field, 25 fields and ~6000 chars per embed).
    """
    fields = []
    for brand, names in groups:
        for idx, chunk in enumerate(chunk_by_length(names)):
            name = f"🥃 {brand}"[:256] if idx == 0 else f"🥃 {brand} (cont.)"[:256]
            fields.append((name, "\n".join(chunk)))

    embeds, current, used = [], None, 0
    for name, value in fields:
        size = len(name) + len(value)
        if current is None or len(current.fields) >= EMBED_FIELD_LIMIT or used + size > EMBED_CHAR_BUDGET:
            current = discord.Embed(
                title=title if not embeds else f"{title} (cont.)",
                color=discord.Color.gold(),
            )
            used = len(current.title)
            embeds.append(current)
        current.add_field(name=name, value=value, inline=False)
        used += size
    return embeds


# Load all data at module import time
CATEGORIES, MASHBILLS, BRAND_INDEX, VARIANT_PARENT = load_all()


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
        app_commands.Choice(name=display_brand(brand)[:100], value=brand[:100])
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

    async def send_mashbill(self, interaction: discord.Interaction, mb_name: str):
        """Send a mashbill embed, with the bottles button when it has variants."""
        mb_data = MASHBILLS[mb_name]
        embed = build_mashbill_embed(mb_name, mb_data)
        count = sum(len(v or []) for v in get_variants(mb_data).values())
        view = make_bottles_view(f"{MASHBILL_BUTTON_PREFIX}{mb_name}", count)
        if view:
            await interaction.response.send_message(embed=embed, view=view)
        else:
            await interaction.response.send_message(embed=embed)

    def brand_groups(self, brand_key):
        """[(mashbill, brand display name, [bottle names])] for a brand key."""
        groups = []
        for mb_name in BRAND_INDEX.get(brand_key, []):
            variants = get_variants(MASHBILLS.get(mb_name, {}))
            for brand, names in variants.items():
                if brand.lower().strip() == brand_key and names:
                    groups.append((mb_name, brand, names))
        return groups

    async def send_brand(self, interaction: discord.Interaction, brand_key: str):
        """Send a brand embed, with the bottles button when it combines several bottles."""
        mashbill_names = BRAND_INDEX[brand_key]
        embed = discord.Embed(
            title=f"🏷️ {display_brand(brand_key)}"[:256],
            color=discord.Color.blue(),
        )
        embed.add_field(
            name="Mashbills",
            value="\n".join(f"• {name}" for name in mashbill_names)[:1024],
            inline=False,
        )
        # Searched an original bottle name? Say which entry it's listed under now.
        parents = VARIANT_PARENT.get(brand_key, [])
        if parents:
            embed.add_field(
                name="Listed as",
                value="\n".join(f"• {brand} ({mb})" for mb, brand in parents)[:1024],
                inline=False,
            )
        count = sum(len(names) for _, _, names in self.brand_groups(brand_key))
        view = make_bottles_view(f"{BRAND_BUTTON_PREFIX}{brand_key}", count)
        if view:
            await interaction.response.send_message(embed=embed, view=view)
        else:
            await interaction.response.send_message(embed=embed)

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        """Handle 'Show individual bottles' clicks (works on old messages too)."""
        if interaction.type != discord.InteractionType.component:
            return
        custom_id = (interaction.data or {}).get("custom_id", "")

        if custom_id.startswith(MASHBILL_BUTTON_PREFIX):
            mb_name = custom_id[len(MASHBILL_BUTTON_PREFIX):]
            variants = get_variants(MASHBILLS.get(mb_name, {}))
            title = f"🍾 Bottles in {mb_name}"
            groups = [(brand, names) for brand, names in variants.items() if names]
        elif custom_id.startswith(BRAND_BUTTON_PREFIX):
            brand_key = custom_id[len(BRAND_BUTTON_PREFIX):]
            found = self.brand_groups(brand_key)
            multi = len({mb for mb, _, _ in found}) > 1
            title = f"🍾 {found[0][1]} bottles" if found else "🍾 Bottles"
            groups = [(f"{brand} ({mb})" if multi else brand, names) for mb, brand, names in found]
        else:
            return  # not our button; other cogs' components are handled by their own views

        if not groups:
            await interaction.response.send_message(
                "This list is no longer available (the data may have been reloaded).", ephemeral=True
            )
            return

        # Only the person who clicked sees the list, so the channel doesn't fill up.
        embeds = build_bottle_embeds(title, groups)
        await interaction.response.send_message(embed=embeds[0], ephemeral=True)
        for extra in embeds[1:]:
            await interaction.followup.send(embed=extra, ephemeral=True)

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
                await self.send_mashbill(interaction, matched_name)
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
                await self.send_mashbill(interaction, matches[0])
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
                await self.send_brand(interaction, search_query_lower)
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
                    msg += f"\nDid you mean: {', '.join(display_brand(c) for c in close)}?"
                await interaction.response.send_message(msg, ephemeral=True)
                return

            if len(matching_brands) == 1:
                await self.send_brand(interaction, matching_brands[0])
                return

            # Multiple brand matches - show pick-list
            embed = discord.Embed(
                title=f"🔍 Multiple brands match '{query}'",
                description="Select one from the autocomplete dropdown, or refine your search:",
                color=discord.Color.blue(),
            )
            embed.add_field(
                name="Matches",
                value="\n".join(f"• {display_brand(b)}" for b in matching_brands[:25])[:1024],
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

        # Acknowledge right away: Discord only gives us 3 seconds to respond,
        # and on a slow free host file loading can blow past that (error 10062).
        await interaction.response.defer(ephemeral=True, thinking=True)

        global CATEGORIES, MASHBILLS, BRAND_INDEX, VARIANT_PARENT
        new_categories, new_mashbills, new_index, new_parent = load_all()
        errors = dict(LOAD_ERRORS)

        # Don't wipe good in-memory data with an empty dict from a broken file
        if "rc_codes.json" not in errors:
            CATEGORIES["rc"] = new_categories["rc"]
        if "nbc_codes.json" not in errors:
            CATEGORIES["nbc"] = new_categories["nbc"]
        if "mashbills.json" not in errors:
            MASHBILLS = new_mashbills
            BRAND_INDEX = new_index
            VARIANT_PARENT = new_parent

        summary = (
            f"RC codes: {len(CATEGORIES['rc'])}\n"
            f"NBC codes: {len(CATEGORIES['nbc'])}\n"
            f"Mashbills: {len(MASHBILLS)}\n"
            f"Brands: {len(BRAND_INDEX)}"
        )
        if errors:
            msg = "⚠️ Reloaded with problems (kept the previous data for any broken file):\n"
            msg += "\n".join(f"• {e}" for e in errors.values())
            msg += f"\n\n{summary}"
        else:
            msg = f"✅ Data reloaded successfully!\n{summary}"

        await interaction.followup.send(msg[:2000], ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(LookupCog(bot))