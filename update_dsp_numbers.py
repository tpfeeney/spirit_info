"""
Teach the bot new DSP registry numbers (DSP-KY-113 and friends) from label
filings (COLAs) your ttb-scraper collects.

    python update_dsp_numbers.py <file-or-folder> [more files/folders...]

Accepts .json (a list of records, or an object holding one), .jsonl, and .csv.
Each record should be one COLA with its plant registry number and the
applicant's name and address; field names are detected automatically.

What it does:
  * New numbers are added with the applicant's name and town, and linked to the
    matching plant in data/dsp.json when the match is clear.
  * Numbers a person entered by hand are never renamed. If a filing names a
    different business, it's reported so you can check.
  * Records it has already learned from (by TTB ID) are skipped, so it's safe
    to run on the same files every day.

The bot notices the updated file within a few minutes on its own.
"""

import csv
import json
import os
import sys

import dsp_registry as R

SEEN_FILE = os.path.join(R.DATA_DIR, "dsp_learned_ids.txt")


def read_records(path):
    if path.endswith(".jsonl"):
        with open(path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
    if path.endswith(".json"):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):  # {"records": [...]} or {"<id>": {...}, ...}
            lists = [v for v in data.values() if isinstance(v, list)]
            data = lists[0] if lists else list(data.values())
        return data if isinstance(data, list) else []
    if path.endswith(".csv"):
        with open(path, encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    return []


def expand(paths):
    for path in paths:
        if os.path.isdir(path):
            for root, _, files in os.walk(path):
                for name in sorted(files):
                    if name.endswith((".json", ".jsonl", ".csv")):
                        yield os.path.join(root, name)
        else:
            yield path


def main(paths):
    if not paths:
        sys.exit(__doc__)
    plants = R.load_plants()
    if not plants:
        sys.exit("data/dsp.json is missing or empty; run update_dsp.py first.")
    numbers = R.load_json(R.NUMBERS_FILE, {})
    seen = set()
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, encoding="utf-8") as f:
            seen = {line.strip() for line in f if line.strip()}

    fresh, total = [], 0
    for path in expand(paths):
        try:
            records = read_records(path)
        except (OSError, ValueError) as e:
            print(f"Skipping {path}: {e}")
            continue
        for rec in records:
            if not isinstance(rec, dict):
                continue
            total += 1
            ttb_id = str(R._pick(rec, "ttb_id", "ttbid", "cola_id") or "").strip()
            if ttb_id and ttb_id in seen:
                continue
            fresh.append(rec)
            if ttb_id:
                seen.add(ttb_id)

    # Records that mention a DSP number but couldn't be used (usually: no applicant name/address)
    unusable = sum(
        1 for rec in fresh
        if R.parse_cola_record(rec) is None and any(R.find_registries(v) for v in rec.values() if isinstance(v, str))
    )

    before = len(numbers)
    changes = R.learn_from_colas(fresh, numbers, plants)
    R.save_json(R.NUMBERS_FILE, numbers)
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(sorted(seen)))

    print(f"Read {total} records ({len(fresh)} new). DSP numbers: {before} -> {len(numbers)}.")
    if unusable:
        print(f"  {unusable} new record(s) had a DSP number but no clear applicant name/address, "
              f"or listed several numbers, so they were skipped.")
    for line in changes:
        print("  " + line)


if __name__ == "__main__":
    main(sys.argv[1:])
