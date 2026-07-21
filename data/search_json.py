#!/usr/bin/env python3
"""
Generic JSON entry search tool.

Works with any JSON file shaped as either:
  - an object of key -> entry     e.g. {"RIO": {...}, "NIO": {...}}
  - an array of entries           e.g. [{...}, {...}]

and searches recursively through every field of every entry (including
nested objects and lists), so it doesn't care what fields your JSON
happens to have — new files with different schemas work out of the box.

Usage:
    python3 search_json.py file1.json [file2.json ...]
        Interactive mode: type queries, see results, 'q' to quit.

    python3 search_json.py file1.json [file2.json ...] -q "query"
        One-shot mode: run a single query and exit (handy for piping /
        scripting / grabbing a quick answer).

You can pass as many files as you want at once (e.g. all three of your
bourbon code files) and it searches across all of them together, showing
which file each match came from.

Query syntax:
    word                    matches if "word" appears (case-insensitive)
                            anywhere in the entry's key or any field value
    field:word              only match within a field whose name contains
                            "field" (e.g. source:mgp, confirmed:true)
    "quoted phrase"          multi-word phrase, still case-insensitive
    word1 word2              multiple terms = AND (all must match)
    -word                    exclude entries containing this term
    -field:word              exclude entries where that field matches

Examples:
    MGP confirmed:true
    source:barton -confirmed:false
    "Kelvin char 4"
    _key:xx                (search the entry's key/name itself)

Matching is fuzzy, in two ways:
  - Compound terms (containing /, -, etc.) are split into pieces, and a
    field matches if every piece appears somewhere in it, not necessarily
    contiguous. So "80c/8r" finds "80C/12MB/8R" even though "12MB" sits
    in between.
  - Single-word terms also tolerate small typos (e.g. "bartn" still finds
    "Barton") via character-level similarity.
"""

import json
import re
import sys
import shlex
from difflib import SequenceMatcher


def load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def iter_entries(data, filename):
    """Yield (label, entry, filename) for each entry, regardless of top-level shape."""
    if isinstance(data, dict):
        for k, v in data.items():
            yield k, v, filename
    elif isinstance(data, list):
        for i, v in enumerate(data):
            label = None
            if isinstance(v, dict):
                for key_candidate in ("name", "id", "key", "title"):
                    if key_candidate in v:
                        label = str(v[key_candidate])
                        break
            yield (label or f"[{i}]"), v, filename
    else:
        yield None, data, filename


def flatten_text(value, path=""):
    """Yield (field_path, text) for every scalar found anywhere inside value."""
    if isinstance(value, dict):
        for k, v in value.items():
            new_path = f"{path}.{k}" if path else k
            yield from flatten_text(v, new_path)
    elif isinstance(value, list):
        for item in value:
            yield from flatten_text(item, path)  # list items share the field's path
    else:
        yield path, "" if value is None else str(value)


def parse_query(query):
    """Parse a query string into a list of (negate, field_filter_or_None, term)."""
    terms = []
    for tok in shlex.split(query):
        negate = tok.startswith("-")
        if negate:
            tok = tok[1:]
        field = None
        if ":" in tok:
            field, tok = tok.split(":", 1)
        terms.append((negate, field.lower() if field else None, tok.lower()))
    return terms


def field_matches(term, text, typo_threshold=0.82):
    """Tiered fuzzy match of `term` against `text`. term/text are already lowercase."""
    if term in text:
        return True  # exact substring - fast path, covers most queries

    # Compound term (has punctuation like "/", "-"): require every piece
    # to appear somewhere in this field, not necessarily contiguous.
    parts = [p for p in re.split(r"[^a-z0-9]+", term) if p]
    if len(parts) > 1:
        return all(p in text for p in parts)

    # Single-word term: tolerate small typos via character-level similarity
    # against each word in the field. Skip very short words, and require
    # word lengths to be close to the term's, so this catches real typos
    # ("bartn" -> "barton") without conflating distinct similar-looking
    # names ("barton" vs "bardstown" - a different distillery entirely).
    words = [
        w for w in re.split(r"[^a-z0-9]+", text)
        if len(w) >= 3 and abs(len(w) - len(term)) <= 2
    ]
    return any(SequenceMatcher(None, term, w).ratio() >= typo_threshold for w in words)


def entry_matches(entry, label, terms):
    pairs = list(flatten_text(entry))
    pairs.append(("_key", label or ""))  # let the entry's own key be searchable too

    for negate, field_filter, term in terms:
        found = any(
            (not field_filter or field_filter in field_path.lower())
            and field_matches(term, text.lower())
            for field_path, text in pairs
        )
        if negate == found:  # negate & found -> bad, or not negate & not found -> bad
            return False
    return True


def print_result(label, entry, filename):
    print(f"\n[{filename}] {label}")
    print(json.dumps(entry, indent=2, ensure_ascii=False))


def run_query(all_entries, query):
    terms = parse_query(query)
    if not terms:
        print("(empty query)")
        return
    count = 0
    for label, entry, filename in all_entries:
        if entry_matches(entry, label, terms):
            print_result(label, entry, filename)
            count += 1
    print(f"\n{count} match(es) for: {query}")


def main():
    args = sys.argv[1:]
    if not args:
        print("Usage: python3 search_json.py file1.json [file2.json ...] [-q QUERY]")
        return

    query = None
    if "-q" in args:
        idx = args.index("-q")
        query = args[idx + 1] if idx + 1 < len(args) else None
        files = args[:idx] + args[idx + 2:]
    else:
        files = args

    if not files:
        print("No files given.")
        return

    all_entries = []
    for path in files:
        try:
            data = load(path)
        except (json.JSONDecodeError, OSError) as e:
            print(f"⚠️  Could not load {path}: {e}")
            continue
        all_entries.extend(iter_entries(data, path))

    print(f"Loaded {len(all_entries)} entries from {len(files)} file(s).")

    if query is not None:
        run_query(all_entries, query)
        return

    print("Type a search query ('q' to quit). See the top of this script for query syntax.\n")
    while True:
        try:
            query = input("search> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if query.lower() in ("q", "quit", "exit"):
            break
        if not query:
            continue
        run_query(all_entries, query)


if __name__ == "__main__":
    main()