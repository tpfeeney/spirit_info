"""
DSP registry numbers (the "DSP-KY-113" printed on labels) and how they connect
to TTB's permit list (data/dsp.json, where Buffalo Trace is "KY-S-9").

Used by update_dsp_numbers.py (learning from label filings) and by the bot.
Standard library only, so it runs anywhere Python 3.9+ does.

data/dsp_numbers.json looks like:

{
  "DSP-KY-113": {
    "name": "Buffalo Trace Distillery",
    "location": "Frankfort, KY",
    "permits": ["KY-S-9"],          # matching plant(s) in dsp.json, if known
    "note": "",                     # anything worth knowing, e.g. disagreements
    "sources": ["Starter list", "Straightbourbon (2006)"],
    "manual": true,                 # true = typed in by a person; the learner never changes the name
    "cola": {                       # filled in by the learner from label filings
      "applicants": {"BUFFALO TRACE DISTILLERY, INC. | FRANKFORT KY": 12},
      "first_seen": "2026-10-20",
      "last_seen": "2026-10-20",
      "example_ttb_id": "26293001000123"
    }
  }
}
"""

import json
import os
import re
from datetime import date

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
NUMBERS_FILE = os.path.join(DATA_DIR, "dsp_numbers.json")
PLANTS_FILE = os.path.join(DATA_DIR, "dsp.json")

# "DSP-KY-113", "DSP KY 113", "D.S.P. KY-113", "dsp-ky-#113"
REGISTRY_RE = re.compile(r"\bD\.?\s*S\.?\s*P\.?[\s\-#:.]*([A-Z]{2})[\s\-#:.]*(\d{1,6})\b", re.IGNORECASE)
# "KY-113" / "KY 113" with no DSP prefix and no "-S-" (that would be a TTB permit number)
BARE_REGISTRY_RE = re.compile(r"^\s*([A-Z]{2})[\s\-#:.]*(\d{1,6})\s*$", re.IGNORECASE)

# Words too common to tell two businesses apart
STOPWORDS = {
    "LLC", "LLLP", "LLP", "LP", "INC", "INCORPORATED", "CO", "CORP", "CORPORATION", "COMPANY", "LTD",
    "THE", "OF", "AND", "DBA", "D/B/A", "A", "DISTILLERY", "DISTILLERIES", "DISTILLING", "DISTILLERS",
    "SPIRITS", "SPIRIT", "BREWERY", "BREWING", "WINERY", "VINEYARD", "VINEYARDS", "GROUP", "HOLDINGS",
    "ENTERPRISES", "BRANDS", "BEVERAGE", "BEVERAGES", "INTERNATIONAL", "USA", "AMERICA", "AMERICAS",
}


_KEEP_UPPER = {"LLC", "LLLP", "LLP", "LP", "II", "III", "IV", "USA", "US", "DBA", "MGP", "MGPI"}
_KEEP_LOWER = {"of", "and", "the", "at", "on", "in", "for"}


def tidy_name(text: str) -> str:
    """'TIGERSHINE COPPER DISTILLERY, LLC' -> 'Tigershine Copper Distillery, LLC'."""
    words = []
    for i, w in enumerate(" ".join(str(text or "").split()).lower().split(" ")):
        if re.sub(r"[^a-z]", "", w).upper() in _KEEP_UPPER:
            w = w.upper()
        elif i and w in _KEEP_LOWER:
            pass
        else:
            w = "-".join(part[:1].upper() + part[1:] for part in w.split("-"))
        words.append(w)
    return " ".join(words)


def registry_key(state: str, number) -> str:
    return f"DSP-{state.upper()}-{int(number)}"


def parse_registry(text):
    """Return 'DSP-KY-113' if text is a DSP registry number in any common format, else None."""
    text = str(text or "")
    m = REGISTRY_RE.search(text) or BARE_REGISTRY_RE.match(text)
    return registry_key(m.group(1), m.group(2)) if m else None


def find_registries(text):
    """Every distinct DSP registry number in a block of text, in order."""
    seen = []
    for m in REGISTRY_RE.finditer(str(text or "")):
        key = registry_key(m.group(1), m.group(2))
        if key not in seen:
            seen.append(key)
    return seen


def name_tokens(name: str) -> set:
    words = re.findall(r"[A-Z0-9']+", str(name or "").upper().replace("&", " AND "))
    words = [re.sub(r"'S$", "", w).strip("'") for w in words]  # "ALLTECH'S" -> "ALLTECH"
    return {w for w in words if w and w not in STOPWORDS}


def name_similarity(a: str, b: str) -> float:
    """Share of distinguishing words two names have in common (0 to 1)."""
    ta, tb = name_tokens(a), name_tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def match_plant(name, state, plants, city="", zip_code="", number=None):
    """
    Find the TTB plant that a (name, place) most likely is. Returns a list of
    permit numbers: one when confident, several when they're equally good
    (e.g. a company with two permits in one town), empty when unsure.
    """
    state = (state or "").upper()
    city = (city or "").upper().strip()
    zip5 = re.sub(r"\D", "", str(zip_code or ""))[:5]
    scored = []
    for permit, p in plants.items():
        if p.get("state") != state:
            continue
        sim = max(name_similarity(name, p.get("operating_name", "")), name_similarity(name, p.get("owner", "")))
        if sim < 0.5:
            continue
        score = sim * 2
        if zip5 and str(p.get("zip", ""))[:5] == zip5:
            score += 2
        elif city and p.get("city", "").upper() == city:
            score += 1.5
        elif city or zip5:
            score -= 1  # named a different town
        if number is not None and permit.endswith(f"-{int(number)}"):
            score += 0.5  # newer plants often share the number; a tiebreaker, not proof
        scored.append((score, permit))
    if not scored:
        return []
    scored.sort(reverse=True)
    best = scored[0][0]
    if best < 2.0:
        return []
    return [permit for score, permit in scored if score >= best - 0.01][:3]


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, sort_keys=True)
    os.replace(tmp, path)


def load_plants():
    raw = load_json(PLANTS_FILE, {})
    plants = raw.get("plants") if isinstance(raw, dict) else None
    return plants if isinstance(plants, dict) else {}


# ==================== LEARNING FROM LABEL FILINGS (COLAs) ====================
CITY_STATE_ZIP_RE = re.compile(r"([A-Z][A-Z .'\-]+?),?\s+([A-Z]{2})\s+(\d{5})(?:-\d{4})?\s*$", re.IGNORECASE)


def _pick(record, *keywords, exclude=()):
    """First non-empty value whose key contains one of the keywords (case-insensitive)."""
    for key, value in record.items():
        k = str(key).lower().replace(" ", "_")
        if any(x in k for x in exclude):
            continue
        if any(word in k for word in keywords) and str(value or "").strip():
            return value
    return ""


def parse_cola_record(record: dict):
    """
    Pull (registry number, applicant name, city, state, zip, ttb_id) out of one
    COLA record, whatever the scraper calls its fields. Returns None when the
    record doesn't clearly name exactly one DSP number for the applicant.
    """
    # The principal plant number. Records sometimes list "other" plants too;
    # those don't belong to the applicant's address, so they're ignored here.
    principal = _pick(record, "principal", exclude=("name", "address"))
    if not principal:
        principal = _pick(record, "plant_registry", "permit", "registry", "plant", exclude=("other",))
    numbers = find_registries(principal)
    if len(numbers) != 1:
        return None
    number = numbers[0]

    name = str(_pick(record, "applicant_name", "company_name", "permittee", "applicant", "company",
                     exclude=("address", "email", "phone", "mailing")) or "").strip()
    city = str(_pick(record, "city") or "").strip()
    state = str(_pick(record, "state", exclude=("statement",)) or "").strip()
    zip_code = str(_pick(record, "zip", "postal") or "").strip()

    # Many scrapers keep the whole "name and address" block as one string
    block = str(_pick(record, "name_and_address", "address", exclude=("mailing", "email")) or "")
    lines = [ln.strip() for ln in re.split(r"[\r\n]+", block) if ln.strip()]
    if lines:
        if not name:
            name = lines[0]
        m = CITY_STATE_ZIP_RE.search(lines[-1])
        if m:
            city = city or m.group(1).strip()
            state = state or m.group(2)
            zip_code = zip_code or m.group(3)

    state = state.upper()[:2]
    if not name or not state:
        return None
    # The DSP number's state must match the applicant's state, or the pairing is suspect
    if number.split("-")[1] != state:
        return None
    ttb_id = str(_pick(record, "ttb_id", "ttbid", "cola_id") or "").strip()
    return number, " ".join(name.upper().split()), city.upper(), state, zip_code, ttb_id


def learn_from_colas(records, numbers: dict, plants: dict, today=None):
    """
    Add what label filings reveal to `numbers` (changed in place). Never renames
    an entry a person typed in; disagreements are recorded for review instead.
    Returns a list of human-readable changes.
    """
    today = today or date.today().isoformat()
    changes = []
    for record in records:
        if not isinstance(record, dict):
            continue
        parsed = parse_cola_record(record)
        if not parsed:
            continue
        number, applicant, city, state, zip_code, ttb_id = parsed
        label = f"{applicant} | {city} {state}".strip()

        entry = numbers.get(number)
        is_new = entry is None
        if is_new:
            entry = numbers[number] = {
                "name": tidy_name(applicant),
                "location": f"{city.title()}, {state}" if city else state,
                "permits": [],
                "note": "",
                "sources": ["Label filings (COLA)"],
                "manual": False,
            }

        cola = entry.setdefault("cola", {"applicants": {}, "first_seen": today})
        cola["applicants"][label] = cola["applicants"].get(label, 0) + 1
        cola["last_seen"] = today
        if ttb_id and not cola.get("example_ttb_id"):
            cola["example_ttb_id"] = ttb_id
        if "Label filings (COLA)" not in entry.setdefault("sources", []):
            entry["sources"].append("Label filings (COLA)")

        if not entry.get("permits"):
            permits = match_plant(applicant, state, plants, city, zip_code, number.split("-")[2])
            if permits:
                entry["permits"] = permits
                changes.append(f"{number}: linked to TTB permit {', '.join(permits)}")

        if is_new:
            changes.append(f"{number}: NEW — {applicant}, {city} {state}")
        elif entry.get("manual") and name_similarity(applicant, entry.get("name", "")) < 0.5 \
                and cola["applicants"][label] == 1:
            changes.append(f"{number}: label filing names {applicant} ({city} {state}), "
                           f"but the list says {entry.get('name')} — worth a look")
    return changes
