#!/usr/bin/env python3
"""Refresh data/advisories.json from the US State Department's travel advisory feed.

The feed lists recently issued or updated advisories, so running this daily
catches every change. For each feed item that matches a country on the map,
the stored level and issue date are updated. Nothing else in the file changes.

Usage: python3 scripts/update_advisories.py [--dry-run]
Uses only the Python standard library.
"""
import datetime
import email.utils
import json
import re
import sys
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

FEED = "https://travel.state.gov/_res/rss/TAsTWs.xml"
ROOT = Path(__file__).resolve().parent.parent
ADVISORIES = ROOT / "data" / "advisories.json"
COUNTRIES = ROOT / "data" / "countries.json"
# Write a fresh "checked" date at least this often, even when no level changed,
# so the app never shows a stale check date for long.
HEARTBEAT_DAYS = 7

# State Department names that differ from the names on the map
ALIASES = {
    "burma": "myanmar", "burma myanmar": "myanmar",
    "democratic republic of the congo": "democratic republic of the congo",
    "democratic republic of the congo drc": "democratic republic of the congo",
    "drc": "democratic republic of the congo",
    "republic of congo": "republic of the congo", "republic of the congo": "republic of the congo",
    "cote divoire": "cote divoire", "cote divoire ivory coast": "cote divoire", "ivory coast": "cote divoire",
    "north korea": "north korea", "north korea democratic peoples republic of korea": "north korea",
    "democratic peoples republic of korea": "north korea",
    "south korea": "south korea", "republic of korea": "south korea",
    "republic of north macedonia": "north macedonia",
    "the bahamas": "bahamas", "the gambia": "gambia",
    "turkey turkiye": "turkey", "turkiye": "turkey",
    "eswatini swaziland": "eswatini", "swaziland": "eswatini",
    "kyrgyz republic": "kyrgyzstan",
    "czech republic": "czechia",
    "timor leste": "timor leste", "east timor": "timor leste",
    # Palestine on the map covers both of these advisories
    "gaza": "palestine", "the west bank": "palestine", "west bank": "palestine",
    "israel the west bank and gaza": "israel",
}


def norm(name):
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    return s


def parse_item(item):
    """Return (country name, level, ISO date) from one feed item, or None."""
    title = (item.findtext("title") or "").strip()
    m = re.match(r"^(.*?)\s*[-–—|:]\s*Level\s*([1-4])\b", title, re.I)
    if not m:
        return None
    name, level = m.group(1).strip(), int(m.group(2))
    date = None
    pub = item.findtext("pubDate")
    if pub:
        try:
            date = email.utils.parsedate_to_datetime(pub).date().isoformat()
        except (TypeError, ValueError):
            date = None
    return name, level, date


def fetch_feed():
    req = urllib.request.Request(FEED, headers={"User-Agent": "HelloWorld-advisory-refresh/1.0 (personal travel map)"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def main():
    dry = "--dry-run" in sys.argv
    countries = json.loads(COUNTRIES.read_text(encoding="utf-8"))
    by_name = {norm(v["name"]): k for k, v in countries.items()}
    data = json.loads(ADVISORIES.read_text(encoding="utf-8"))
    stored = data.setdefault("countries", {})

    root = ET.fromstring(fetch_feed())
    items = root.findall(".//item")
    if not items:
        sys.exit("The feed came back with no items; leaving the advisories unchanged.")

    # Several feed items can map to one map country (Gaza and the West Bank both
    # map to Palestine). Keep the highest level for each country.
    found, unmatched = {}, []
    for it in items:
        parsed = parse_item(it)
        if not parsed:
            continue
        name, level, date = parsed
        key = ALIASES.get(norm(name), norm(name))
        cid = by_name.get(key)
        if not cid:
            unmatched.append(name)
            continue
        prev = found.get(cid)
        if not prev or level > prev[0] or (level == prev[0] and (date or "") > (prev[1] or "")):
            found[cid] = (level, date, name)

    changes = []
    for cid, (level, date, src) in sorted(found.items()):
        old = stored.get(cid, {})
        if old.get("level") == level and (not date or old.get("issued", "") >= date):
            continue
        entry = {"level": level}
        if date:
            entry["issued"] = date
        if "note" in old and old.get("level") == level:
            entry["note"] = old["note"]   # keep hand-written notes only while the level is unchanged
        stored[cid] = entry
        changes.append(f"{countries[cid]['name']}: Level {old.get('level', '?')} -> {level}" + (f" (issued {date})" if date else "") + f"  [{src}]")

    today = datetime.date.today().isoformat()
    last = data.get("checked", "2000-01-01")
    stale = (datetime.date.fromisoformat(today) - datetime.date.fromisoformat(last)).days >= HEARTBEAT_DAYS

    print(f"Feed items: {len(items)}; matched to the map: {len(found)}; not on the map: {len(unmatched)}")
    if unmatched:
        print("Not on the map (fine for territories; add an alias if a real country shows up here):")
        for n in sorted(set(unmatched)):
            print("  -", n)
    print("Changes:" if changes else "No level changes.")
    for c in changes:
        print("  -", c)

    if dry:
        print("Dry run: nothing written.")
        return
    if changes or stale:
        data["checked"] = today
        ADVISORIES.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Wrote {ADVISORIES.relative_to(ROOT)} (checked {today}).")
    else:
        print("Nothing to write.")


if __name__ == "__main__":
    main()
