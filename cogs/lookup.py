import discord
from discord import app_commands
from discord.ext import commands, tasks
import json
import os
import re
from collections import Counter
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


def normalize_term(text):
    """Lowercase and straighten curly apostrophes so "L'Burg" finds "L’Burg"."""
    return str(text).replace("\u2019", "'").replace("\u2018", "'").strip().lower()


def build_acronym_index(acronyms):
    """Map every spelling of an acronym (the entry key and each alias) to the entry keys it belongs to."""
    index = {}
    for key, entry in acronyms.items():
        if not isinstance(entry, dict):
            continue
        for name in [key] + list(entry.get("aliases") or []):
            norm = normalize_term(name)
            if norm and key not in index.setdefault(norm, []):
                index[norm].append(key)
    return index


def acronym_meaning(entry):
    return str(entry.get("meaning") or "Unknown") if isinstance(entry, dict) else "Unknown"


def build_acronym_embed(key, entry):
    """Embed for one acronym: the term, what it stands for, and any note."""
    embed = discord.Embed(
        title=f"🔤 {key}"[:256],
        description=f"**{acronym_meaning(entry)}**"[:4096],
        color=discord.Color.teal(),
    )
    note = entry.get("note") if isinstance(entry, dict) else None
    if note:
        embed.add_field(name="Note", value=str(note)[:1024], inline=False)
    return embed


# ==================== DISTILLED SPIRITS PLANTS ====================
US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "PR": "Puerto Rico", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont",
    "VA": "Virginia", "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}
DSP_PAGE_SIZE = 20
DSP_PERMIT_NOTE = "TTB basic permit number, not the DSP registry number printed on labels"

# Words that should stay in capitals when tidying TTB's ALL-CAPS text
_KEEP_UPPER = {"LLC", "LLLP", "LLP", "LP", "II", "III", "IV", "USA", "US", "DBA", "NE", "NW", "SE", "SW",
               "PO", "FM", "HWY", "CR", "SR", "RR", "MGP", "MGPI", "NOLA", "NYC"}


_KEEP_LOWER = {"of", "and", "the", "at", "on", "in", "for", "&"}


def _tidy_word(word: str) -> str:
    if re.sub(r"[^A-Za-z]", "", word).upper() in _KEEP_UPPER:
        return word.upper()
    # Capitalize each part of hyphenated names: "brown-forman" -> "Brown-Forman"
    return "-".join(part[:1].upper() + part[1:] for part in word.split("-"))


def tidy(text) -> str:
    """Turn TTB's ALL-CAPS text into normal capitalization; leave text that's already mixed case alone."""
    text = " ".join(str(text or "").split())
    letters = [c for c in text if c.isalpha()]
    if not letters or sum(c.isupper() for c in letters) / len(letters) < 0.8:
        return text
    words = [_tidy_word(w) for w in text.lower().split(" ")]
    return " ".join(w.lower() if i and w.lower() in _KEEP_LOWER else w for i, w in enumerate(words))


def permit_key(text) -> str:
    """'ky-s-9', 'KY S 9' and 'KYS9' all become 'KYS9'."""
    return re.sub(r"[^A-Z0-9]", "", str(text).upper())


def dsp_name(plant) -> str:
    return tidy(plant.get("operating_name") or plant.get("owner") or "Unknown")


def dsp_place(plant) -> str:
    return f"{tidy(plant.get('city', ''))}, {plant.get('state', '')}".strip(", ")


def build_dsp(raw):
    """From dsp.json, build (plants, as_of, by_owner, search_text, permit_keys)."""
    plants = raw.get("plants") if isinstance(raw.get("plants"), dict) else {}
    plants = {k: v for k, v in plants.items() if isinstance(v, dict)}
    by_owner, search_text, keys = {}, {}, {}
    for permit, p in plants.items():
        by_owner.setdefault(normalize_term(p.get("owner", "")), []).append(permit)
        search_text[permit] = normalize_term(" | ".join([
            permit, p.get("operating_name", ""), p.get("owner", ""), p.get("city", ""),
        ]))
        keys[permit_key(permit)] = permit
    return plants, str(raw.get("as_of") or "unknown date"), by_owner, search_text, keys


# DSP registry numbers: the "DSP-KY-113" printed on labels (data/dsp_numbers.json).
# "DSP-KY-113", "DSP KY 113", "D.S.P. KY-113"; also bare "KY-113" (no "-S-", which would be a permit)
REGISTRY_RE = re.compile(r"\bD\.?\s*S\.?\s*P\.?[\s\-#:.]*([A-Z]{2})[\s\-#:.]*(\d{1,6})\b", re.IGNORECASE)
BARE_REGISTRY_RE = re.compile(r"^\s*([A-Z]{2})[\s\-#:.]*(\d{1,6})\s*$", re.IGNORECASE)
REGISTRY_FOOTER = "DSP numbers come from community lists and label filings, not an official TTB list"


def parse_registry(text):
    m = REGISTRY_RE.search(str(text or "")) or BARE_REGISTRY_RE.match(str(text or ""))
    return f"DSP-{m.group(1).upper()}-{int(m.group(2))}" if m else None


def registry_sort_key(number):
    parts = number.split("-")
    return (parts[1], int(parts[2])) if len(parts) == 3 and parts[2].isdigit() else (number, 0)


def build_registry(raw):
    """From dsp_numbers.json, build (numbers, by_permit) where by_permit maps a TTB permit to its DSP numbers."""
    numbers = {k: v for k, v in raw.items() if isinstance(v, dict) and parse_registry(k) == k}
    by_permit = {}
    for number in sorted(numbers, key=registry_sort_key):
        for permit in numbers[number].get("permits") or []:
            by_permit.setdefault(permit, []).append(number)
    return numbers, by_permit


def registry_label(number, entry):
    place = f" ({entry['location']})" if entry.get("location") else ""
    return f"{number} — {entry.get('name') or 'Unknown'}{place}"


def build_registry_embed(number, entry, plants):
    embed = discord.Embed(
        title=f"🏷️ {number}",
        description=f"**{entry.get('name') or 'Unknown'}**" + (f"\n{entry['location']}" if entry.get("location") else ""),
        color=discord.Color.dark_gold(),
    )
    if entry.get("note"):
        embed.add_field(name="Note", value=str(entry["note"])[:1024], inline=False)
    lines = []
    for permit in entry.get("permits") or []:
        p = plants.get(permit)
        if p:
            street = tidy(p.get("street", ""))
            lines.append(f"• {dsp_name(p)} — {street + ', ' if street else ''}{dsp_place(p)} (`{permit}`)")
    if lines:
        name = "TTB permit" if len(lines) == 1 else "Possible TTB permits"
        embed.add_field(name=name, value="\n".join(lines)[:1024], inline=False)
    applicants = (entry.get("cola") or {}).get("applicants") or {}
    if applicants:
        top = sorted(applicants.items(), key=lambda kv: -kv[1])[:3]
        embed.add_field(
            name="Seen on label filings",
            value="\n".join(f"• {tidy(a.replace(' | ', ', '))} ({n})" for a, n in top)[:1024],
            inline=False,
        )
    if entry.get("sources"):
        embed.add_field(name="Sources", value=", ".join(entry["sources"])[:1024], inline=False)
    embed.set_footer(text=f"{REGISTRY_FOOTER} · Know a fix? /suggest")
    return embed


def resolve_state(text):
    """'KY', 'ky' or 'Kentucky' -> 'KY'; None if it isn't a state."""
    t = str(text or "").strip()
    if t.upper() in US_STATES:
        return t.upper()
    for code, name in US_STATES.items():
        if name.lower() == t.lower():
            return code
    return None


def dsp_footer(as_of) -> str:
    return f"TTB list of permittees · data as of {as_of}"


def build_dsp_embed(permit, plant, as_of, by_owner, plants, registry_numbers=()):
    """Embed for one distilled spirits plant."""
    embed = discord.Embed(title=f"🏭 {dsp_name(plant)}"[:256], color=discord.Color.dark_gold())
    owner = tidy(plant.get("owner", ""))
    if plant.get("operating_name") and owner and not owner.lower().startswith(dsp_name(plant).lower()):
        embed.description = f"Owned by **{owner}**"
    embed.add_field(name="Permit", value=f"`{permit}`", inline=True)
    if registry_numbers:
        embed.add_field(name="DSP number", value=", ".join(f"`{n}`" for n in registry_numbers)[:1024], inline=True)
    state = plant.get("state", "")
    embed.add_field(name="State", value=US_STATES.get(state, state) or "Unknown", inline=True)
    if plant.get("county"):
        embed.add_field(name="County", value=tidy(plant["county"]), inline=True)
    address = "\n".join(x for x in [
        tidy(plant.get("street", "")),
        f"{dsp_place(plant)} {plant.get('zip', '')}".strip(),
    ] if x)
    if address:
        embed.add_field(name="Address", value=address[:1024], inline=False)
    if plant.get("new"):
        embed.add_field(name="🆕 New", value="Added since TTB's previous list", inline=False)

    siblings = [p for p in by_owner.get(normalize_term(plant.get("owner", "")), []) if p != permit]
    if siblings:
        siblings.sort(key=lambda k: (dsp_name(plants[k]).lower(), k))
        lines = [f"• {dsp_name(plants[k])} — {dsp_place(plants[k])} (`{k}`)" for k in siblings[:10]]
        if len(siblings) > 10:
            lines.append(f"…and {len(siblings) - 10} more")
        embed.add_field(name=f"Same owner ({len(siblings)} other plant{'s' if len(siblings) != 1 else ''})",
                        value="\n".join(lines)[:1024], inline=False)
    if registry_numbers:
        embed.set_footer(text=f"{dsp_footer(as_of)} · {REGISTRY_FOOTER}")
    else:
        embed.set_footer(text=f"{dsp_footer(as_of)} · Permit is a {DSP_PERMIT_NOTE}")
    return embed


class DspPager(discord.ui.View):
    """Previous / Next buttons for a long list of plants (private to the person who asked)."""

    def __init__(self, pages, user_id):
        super().__init__(timeout=600)
        self.pages, self.user_id, self.index = pages, user_id, 0
        self._sync()

    def _sync(self):
        self.prev_button.disabled = self.index == 0
        self.next_button.disabled = self.index >= len(self.pages) - 1

    async def _show(self, interaction):
        self._sync()
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)

    @discord.ui.button(label="◀ Previous", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = max(0, self.index - 1)
        await self._show(interaction)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = min(len(self.pages) - 1, self.index + 1)
        await self._show(interaction)


def build_dsp_pages(title, permits, plants, as_of, show_city=True, extra_field=None, show_state=False,
                    by_permit=None):
    """Split a list of permits into embeds of DSP_PAGE_SIZE lines each."""
    permits = sorted(permits, key=lambda k: (dsp_name(plants[k]).lower(), k))
    total_pages = max(1, -(-len(permits) // DSP_PAGE_SIZE))
    pages = []
    for i in range(total_pages):
        chunk = permits[i * DSP_PAGE_SIZE:(i + 1) * DSP_PAGE_SIZE]
        lines = []
        for k in chunk:
            if show_state:
                place = f" — {dsp_place(plants[k])}"
            elif show_city:
                place = f" — {tidy(plants[k].get('city', ''))}"
            else:
                place = ""
            new = " 🆕" if plants[k].get("new") else ""
            reg = (by_permit or {}).get(k) or []
            reg_text = f" · {' / '.join(reg[:2])}" if reg else ""
            lines.append(f"• **{dsp_name(plants[k])}**{place} · `{k}`{reg_text}{new}")
        embed = discord.Embed(title=title[:256], description="\n".join(lines)[:4096] or "Nothing here.",
                              color=discord.Color.dark_gold())
        if extra_field and i == 0:
            embed.add_field(name=extra_field[0], value=extra_field[1][:1024], inline=False)
        embed.set_footer(text=f"Page {i + 1}/{total_pages} · {dsp_footer(as_of)} · Details: /lookup type:dsp")
        pages.append(embed)
    return pages


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
    """Load every data file. Returns (categories, mashbills, brand_index, variant_parent, acronyms, dsp_raw, dsp_numbers)."""
    LOAD_ERRORS.clear()
    categories = {
        "rc": load_json("rc_codes.json"),
        "nbc": load_json("nbc_codes.json"),
    }
    mashbills = load_json("mashbills.json")
    acronyms = load_json("acronyms.json")
    dsp_raw = load_json("dsp.json")
    dsp_numbers = load_json("dsp_numbers.json")
    dsp_count = len(dsp_raw.get("plants") or {}) if isinstance(dsp_raw.get("plants"), dict) else 0
    print(
        f"[lookup] Loaded {len(categories['rc'])} RC codes, {len(categories['nbc'])} NBC codes, "
        f"{len(mashbills)} mashbills, {len(acronyms)} acronyms, {dsp_count} DSPs, "
        f"{len(dsp_numbers)} DSP numbers from {DATA_DIR}"
    )
    brand_index, variant_parent = build_brand_index(mashbills)
    return categories, mashbills, brand_index, variant_parent, acronyms, dsp_raw, dsp_numbers


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
CATEGORIES, MASHBILLS, BRAND_INDEX, VARIANT_PARENT, ACRONYMS, _DSP_RAW, _DSP_NUMBERS_RAW = load_all()
ACRONYM_INDEX = build_acronym_index(ACRONYMS)
DSP_PLANTS, DSP_AS_OF, DSP_BY_OWNER, DSP_SEARCH, DSP_KEYS = build_dsp(_DSP_RAW)
DSP_REG, DSP_REG_BY_PERMIT = build_registry(_DSP_NUMBERS_RAW)


def reload_dsp_files():
    """Reload just the two distillery files (used by the automatic check). Returns True if anything changed."""
    global DSP_PLANTS, DSP_AS_OF, DSP_BY_OWNER, DSP_SEARCH, DSP_KEYS, DSP_REG, DSP_REG_BY_PERMIT
    LOAD_ERRORS.pop("dsp.json", None)
    LOAD_ERRORS.pop("dsp_numbers.json", None)
    raw = load_json("dsp.json")
    numbers = load_json("dsp_numbers.json")
    if "dsp.json" not in LOAD_ERRORS:
        DSP_PLANTS, DSP_AS_OF, DSP_BY_OWNER, DSP_SEARCH, DSP_KEYS = build_dsp(raw)
    if "dsp_numbers.json" not in LOAD_ERRORS:
        DSP_REG, DSP_REG_BY_PERMIT = build_registry(numbers)
    print(f"[lookup] Auto-reloaded distillery data: {len(DSP_PLANTS)} plants, {len(DSP_REG)} DSP numbers")


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


async def acronym_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    """Autocomplete for acronyms: matches the acronym itself or what it stands for."""
    query = normalize_term(current)
    ranked = []
    for key, entry in ACRONYMS.items():
        if not isinstance(entry, dict):
            continue
        spellings = [normalize_term(key)] + [normalize_term(a) for a in entry.get("aliases") or []]
        meaning = acronym_meaning(entry)
        if not query:
            rank = 0
        elif any(s.startswith(query) for s in spellings):
            rank = 0  # typed the start of the acronym
        elif any(query in s for s in spellings):
            rank = 1
        elif query in meaning.lower():
            rank = 2  # typed part of the name, e.g. "weller"
        else:
            continue
        ranked.append((rank, key.lower(), key, meaning))
    ranked.sort()
    return [
        app_commands.Choice(name=f"{key} — {meaning}"[:100], value=key[:100])
        for _, _, key, meaning in ranked[:25]
    ]


async def dsp_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    """Autocomplete for plants: matches permit number, operating name, owner or city."""
    query = normalize_term(current)
    if not query:
        return []  # thousands of plants; wait until something is typed
    qkey = permit_key(current)
    ranked = []

    # DSP registry numbers: typed as a number ("dsp-ky-1", "KY-11") or by name
    reg_query = re.sub(r"[^a-z0-9]", "", query)
    for number, entry in DSP_REG.items():
        compact = number.lower().replace("-", "")
        name = str(entry.get("name") or "").lower()
        if compact.startswith(reg_query) or compact[3:].startswith(reg_query):
            ranked.append((-1, registry_sort_key(number), number, registry_label(number, entry)))
        elif len(query) >= 3 and query in name:
            ranked.append((2, registry_sort_key(number), number, registry_label(number, entry)))

    for permit, text in DSP_SEARCH.items():
        plant = DSP_PLANTS[permit]
        name = dsp_name(plant).lower()
        if qkey and permit_key(permit).startswith(qkey):
            rank = 0
        elif name.startswith(query):
            rank = 1
        elif query in name:
            rank = 2
        elif query in text:
            rank = 3
        else:
            continue
        ranked.append((rank, (name, 0), permit, f"{dsp_name(plant)} — {dsp_place(plant)} ({permit})"))
    ranked.sort()
    return [app_commands.Choice(name=label[:100], value=value[:100]) for _, _, value, label in ranked[:25]]


def dsp_state_counts():
    return Counter(p.get("state", "") for p in DSP_PLANTS.values())


async def dsp_state_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    query = current.strip().lower()
    counts = dsp_state_counts()
    results = []
    for code, name in sorted(US_STATES.items(), key=lambda kv: kv[1]):
        if not counts.get(code):
            continue
        if not query or code.lower().startswith(query) or query in name.lower():
            results.append(app_commands.Choice(name=f"{name} ({code}) — {counts[code]} plants", value=code))
    return results[:25]


async def dsp_city_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    state = resolve_state(getattr(interaction.namespace, "state", None))
    if not state:
        return []
    query = current.strip().lower()
    counts = Counter(tidy(p.get("city", "")) for p in DSP_PLANTS.values() if p.get("state") == state)
    ranked = sorted(
        (0 if c.lower().startswith(query) else 1, c)
        for c in counts if c and (not query or query in c.lower())
    )
    return [app_commands.Choice(name=f"{c} ({counts[c]})"[:100], value=c[:100]) for _, c in ranked[:25]]


class LookupCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._dsp_mtimes = self._current_dsp_mtimes()

    @staticmethod
    def _current_dsp_mtimes():
        times = {}
        for name in ("dsp.json", "dsp_numbers.json"):
            try:
                times[name] = os.path.getmtime(os.path.join(DATA_DIR, name))
            except OSError:
                times[name] = None
        return times

    async def cog_load(self):
        self.watch_dsp_files.start()

    async def cog_unload(self):
        self.watch_dsp_files.cancel()

    @tasks.loop(minutes=5)
    async def watch_dsp_files(self):
        """Pick up new distillery data (e.g. numbers the learner added) without needing /reload-data."""
        current = self._current_dsp_mtimes()
        if current != self._dsp_mtimes:
            self._dsp_mtimes = current
            reload_dsp_files()

    @watch_dsp_files.error
    async def watch_dsp_files_error(self, error):
        print(f"[lookup] Error checking distillery files: {error!r}")

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

    @app_commands.command(name="lookup", description="Look up codes, mashbills, brands, acronyms, or distilleries")
    @app_commands.describe(
        type="Choose what to look up",
        query="The code, mashbill, brand, acronym, or distillery/permit to search for"
    )
    @app_commands.choices(type=[
        app_commands.Choice(name="rc", value="rc"),
        app_commands.Choice(name="nbc", value="nbc"),
        app_commands.Choice(name="mashbill", value="mashbill"),
        app_commands.Choice(name="brand", value="brand"),
        app_commands.Choice(name="acronym", value="acronym"),
        app_commands.Choice(name="dsp (distillery)", value="dsp"),
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

        elif lookup_type == "acronym":
            query_norm = normalize_term(search_query)

            # 1. Exact match on the acronym or any of its spellings (e.g. "AAA", "SiB", "L'Burg")
            keys = ACRONYM_INDEX.get(query_norm)
            if keys:
                embeds = [build_acronym_embed(k, ACRONYMS[k]) for k in keys[:10]]
                await interaction.response.send_message(embeds=embeds)
                return

            # 2. Partial match on the acronym or on what it stands for
            matches = []
            for key, entry in ACRONYMS.items():
                if not isinstance(entry, dict):
                    continue
                spellings = [normalize_term(key)] + [normalize_term(a) for a in entry.get("aliases") or []]
                if any(query_norm in s for s in spellings) or query_norm in acronym_meaning(entry).lower():
                    matches.append(key)

            if not matches:
                close = get_close_matches(query_norm, list(ACRONYM_INDEX.keys()), n=3, cutoff=0.6)
                suggestions = []
                for c in close:
                    for k in ACRONYM_INDEX[c]:
                        if k not in suggestions:
                            suggestions.append(k)
                msg = f"❌ No acronym found matching '{query}'"
                if suggestions:
                    msg += f"\nDid you mean: {', '.join(suggestions)}?"
                await interaction.response.send_message(msg, ephemeral=True)
                return

            if len(matches) == 1:
                await interaction.response.send_message(embed=build_acronym_embed(matches[0], ACRONYMS[matches[0]]))
                return

            # 3. Several matches - show them all privately, each with its meaning
            matches.sort(key=str.lower)
            lines = [f"• **{k}** — {acronym_meaning(ACRONYMS[k])}" for k in matches[:25]]
            embed = discord.Embed(
                title=f"🔍 Acronyms matching '{query}'"[:256],
                description="\n".join(lines)[:4096],
                color=discord.Color.teal(),
            )
            if len(matches) > 25:
                embed.set_footer(text=f"Showing 25 of {len(matches)} matches")
            await interaction.response.send_message(embed=embed, ephemeral=True)

        elif lookup_type == "dsp":
            # 1. A DSP registry number ("DSP-KY-113", "dsp ky 113", "KY-113")
            number = parse_registry(search_query)
            if number and (REGISTRY_RE.search(search_query) or not DSP_KEYS.get(permit_key(search_query))):
                entry = DSP_REG.get(number)
                if entry:
                    await interaction.response.send_message(embed=build_registry_embed(number, entry, DSP_PLANTS))
                    return
                state, num = number.split("-")[1], number.split("-")[2]
                msg = f"❓ `{number}` isn't in the list yet."
                same = DSP_KEYS.get(permit_key(f"{state}-S-{num}"))
                if same:
                    msg += (f"\nTTB permit `{same}` is **{dsp_name(DSP_PLANTS[same])}** ({dsp_place(DSP_PLANTS[same])}). "
                            f"For newer plants the two numbers often match, but not always.")
                msg += "\nIf you know which distillery it is, send it in with `/suggest`."
                await interaction.response.send_message(msg, ephemeral=True)
                return

            # 2. Exact permit number, however it's typed ("ky-s-9", "KY S 9")
            permit = DSP_KEYS.get(permit_key(search_query))
            if permit:
                await interaction.response.send_message(
                    embed=build_dsp_embed(permit, DSP_PLANTS[permit], DSP_AS_OF, DSP_BY_OWNER, DSP_PLANTS,
                                          DSP_REG_BY_PERMIT.get(permit, []))
                )
                return

            # 2. A bare state ("KY", "Kentucky") would match hundreds of plants; point to /dsp
            state = resolve_state(search_query)
            if state:
                count = dsp_state_counts().get(state, 0)
                await interaction.response.send_message(
                    f"🗺️ {US_STATES[state]} has {count} distilled spirits plant permits. "
                    f"Browse them with `/dsp state:{state}`.",
                    ephemeral=True,
                )
                return

            # 3. Partial match on name, owner, city or permit
            query_norm = normalize_term(search_query)
            matches = [k for k, text in DSP_SEARCH.items() if query_norm and query_norm in text]
            reg_matches = sorted(
                (n for n, e in DSP_REG.items() if query_norm and query_norm in normalize_term(e.get("name", ""))),
                key=registry_sort_key,
            )
            if not matches and len(reg_matches) == 1:
                n = reg_matches[0]
                await interaction.response.send_message(embed=build_registry_embed(n, DSP_REG[n], DSP_PLANTS))
                return
            if not matches and reg_matches:
                embed = discord.Embed(
                    title=f"🏷️ DSP numbers matching '{query}' ({len(reg_matches)})"[:256],
                    description="\n".join(f"• {registry_label(n, DSP_REG[n])}" for n in reg_matches[:25])[:4096],
                    color=discord.Color.dark_gold(),
                )
                embed.set_footer(text=REGISTRY_FOOTER)
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            if not matches:
                names = {dsp_name(p).lower(): k for k, p in DSP_PLANTS.items()}
                close = get_close_matches(query_norm, list(names), n=3, cutoff=0.6)
                msg = f"❌ No distillery found matching '{query}'"
                if close:
                    msg += "\nDid you mean: " + ", ".join(dsp_name(DSP_PLANTS[names[c]]) for c in close) + "?"
                await interaction.response.send_message(msg, ephemeral=True)
                return
            if len(matches) == 1 and not reg_matches:
                k = matches[0]
                await interaction.response.send_message(
                    embed=build_dsp_embed(k, DSP_PLANTS[k], DSP_AS_OF, DSP_BY_OWNER, DSP_PLANTS,
                                          DSP_REG_BY_PERMIT.get(k, []))
                )
                return

            extra = None
            if reg_matches:
                extra = ("DSP numbers matching",
                         "\n".join(f"• {registry_label(n, DSP_REG[n])}" for n in reg_matches[:10]))
            pages = build_dsp_pages(f"🔍 Distilleries matching '{query}' ({len(matches)})",
                                    matches, DSP_PLANTS, DSP_AS_OF, show_state=True,
                                    extra_field=extra, by_permit=DSP_REG_BY_PERMIT)
            view = DspPager(pages, interaction.user.id) if len(pages) > 1 else discord.utils.MISSING
            await interaction.response.send_message(embed=pages[0], view=view, ephemeral=True)

    @app_commands.command(name="dsp", description="Browse distilled spirits plants by state and city")
    @app_commands.describe(
        state="State to list (leave empty for a count in every state)",
        city="Only show plants in this city (pick a state first)",
    )
    async def dsp(self, interaction: discord.Interaction, state: str = None, city: str = None):
        if not DSP_PLANTS:
            await interaction.response.send_message("❌ Distillery data isn't loaded.", ephemeral=True)
            return

        counts = dsp_state_counts()

        # No state: national overview
        if not state:
            lines = [
                f"`{code}` {US_STATES.get(code, code)} — **{n}**"
                for code, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
            ]
            embed = discord.Embed(
                title=f"🇺🇸 Distilled spirits plants by state ({len(DSP_PLANTS):,} total)",
                description="\n".join(lines)[:4096],
                color=discord.Color.dark_gold(),
            )
            embed.set_footer(text=f"{dsp_footer(DSP_AS_OF)} · Pick a state with /dsp state:")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        code = resolve_state(state)
        if not code or not counts.get(code):
            await interaction.response.send_message(f"❌ No plants found for state '{state}'.", ephemeral=True)
            return

        in_state = [k for k, p in DSP_PLANTS.items() if p.get("state") == code]
        place = US_STATES.get(code, code)

        if city:
            wanted = city.strip().lower()
            picked = [k for k in in_state if tidy(DSP_PLANTS[k].get("city", "")).lower() == wanted]
            if not picked:
                picked = [k for k in in_state if wanted in DSP_PLANTS[k].get("city", "").lower()]
            if not picked:
                await interaction.response.send_message(
                    f"❌ No plants found in a city matching '{city}' in {place}.", ephemeral=True
                )
                return
            cities = sorted({tidy(DSP_PLANTS[k].get("city", "")) for k in picked})
            title = f"🏭 Distilleries in {', '.join(cities[:3])}{'…' if len(cities) > 3 else ''}, {code} ({len(picked)})"
            pages = build_dsp_pages(title, picked, DSP_PLANTS, DSP_AS_OF, show_city=len(cities) > 1,
                                    by_permit=DSP_REG_BY_PERMIT)
        else:
            city_counts = Counter(tidy(DSP_PLANTS[k].get("city", "")) for k in in_state)
            top = ", ".join(f"{c} ({n})" for c, n in city_counts.most_common(8))
            pages = build_dsp_pages(
                f"🏭 Distilleries in {place} ({len(in_state)})", in_state, DSP_PLANTS, DSP_AS_OF,
                extra_field=("Busiest cities", top), by_permit=DSP_REG_BY_PERMIT,
            )

        view = DspPager(pages, interaction.user.id) if len(pages) > 1 else discord.utils.MISSING
        await interaction.response.send_message(embed=pages[0], view=view, ephemeral=True)

    @dsp.autocomplete("state")
    async def dsp_state_ac(self, interaction: discord.Interaction, current: str):
        return await dsp_state_autocomplete(interaction, current)

    @dsp.autocomplete("city")
    async def dsp_city_ac(self, interaction: discord.Interaction, current: str):
        return await dsp_city_autocomplete(interaction, current)

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
        elif type_value == "acronym":
            return await acronym_autocomplete(interaction, current)
        elif type_value == "dsp":
            return await dsp_autocomplete(interaction, current)

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

        global CATEGORIES, MASHBILLS, BRAND_INDEX, VARIANT_PARENT, ACRONYMS, ACRONYM_INDEX
        global DSP_PLANTS, DSP_AS_OF, DSP_BY_OWNER, DSP_SEARCH, DSP_KEYS, DSP_REG, DSP_REG_BY_PERMIT
        new_categories, new_mashbills, new_index, new_parent, new_acronyms, new_dsp, new_numbers = load_all()
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
        if "acronyms.json" not in errors:
            ACRONYMS = new_acronyms
            ACRONYM_INDEX = build_acronym_index(new_acronyms)
        if "dsp.json" not in errors:
            DSP_PLANTS, DSP_AS_OF, DSP_BY_OWNER, DSP_SEARCH, DSP_KEYS = build_dsp(new_dsp)
        if "dsp_numbers.json" not in errors:
            DSP_REG, DSP_REG_BY_PERMIT = build_registry(new_numbers)

        summary = (
            f"RC codes: {len(CATEGORIES['rc'])}\n"
            f"NBC codes: {len(CATEGORIES['nbc'])}\n"
            f"Mashbills: {len(MASHBILLS)}\n"
            f"Brands: {len(BRAND_INDEX)}\n"
            f"Acronyms: {len(ACRONYMS)}\n"
            f"Distilleries (DSPs): {len(DSP_PLANTS)} (TTB data as of {DSP_AS_OF})\n"
            f"DSP numbers: {len(DSP_REG)}"
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