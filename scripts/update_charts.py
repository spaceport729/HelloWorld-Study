#!/usr/bin/env python3
"""Refresh data/charts.json with each country's most-played songs on Apple Music.

Reads Apple's public marketing feed (no key needed), one request per country.
Countries without an Apple Music storefront are skipped. If a country's fetch
fails this time, its previous chart is kept.

Usage: python3 scripts/update_charts.py [--dry-run]
Uses only the Python standard library.
"""
import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from iso_codes import ALPHA2  # noqa: E402

FEED = "https://rss.applemarketingtools.com/api/v2/{cc}/music/most-played/10/songs.json"
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "charts.json"
COUNTRIES = ROOT / "data" / "countries.json"
# Apple's feed should answer for well over this many map countries; fewer means something broke.
MIN_EXPECTED = 40


def fetch(cc):
    req = urllib.request.Request(FEED.format(cc=cc), headers={"User-Agent": "HelloWorld-charts/1.0 (personal culture map)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def main():
    dry = "--dry-run" in sys.argv
    countries = json.loads(COUNTRIES.read_text(encoding="utf-8"))
    old = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    prev = old.get("countries", {})
    out = {}
    no_store, failed = [], []

    for cid in sorted(countries):
        cc = ALPHA2.get(cid)
        if not cc:
            continue
        try:
            feed = fetch(cc).get("feed", {})
        except urllib.error.HTTPError as e:
            if e.code == 404:
                no_store.append(countries[cid]["name"])   # no Apple Music storefront there
            else:
                failed.append(f"{countries[cid]['name']} (HTTP {e.code})")
                if cid in prev:
                    out[cid] = prev[cid]
            continue
        except Exception as e:  # network hiccup or bad JSON: keep last week's chart
            failed.append(f"{countries[cid]['name']} ({type(e).__name__})")
            if cid in prev:
                out[cid] = prev[cid]
            continue
        finally:
            time.sleep(0.25)   # be gentle with Apple's servers

        songs = []
        for r in feed.get("results", [])[:10]:
            if r.get("name") and r.get("url"):
                songs.append({"name": r["name"], "artist": r.get("artistName", ""), "url": r["url"]})
        if songs:
            updated = (feed.get("updated") or "")[:10] or datetime.date.today().isoformat()
            out[cid] = {"updated": updated, "songs": songs}

    print(f"Charts for {len(out)} countries; no Apple Music storefront: {len(no_store)}; failed this run: {len(failed)}")
    sample = [f"{countries[c]['name']}: {out[c]['songs'][0]['name']} by {out[c]['songs'][0]['artist']}" for c in ("620", "484", "392") if c in out]
    for line in sample:
        print("  #1 in", line)
    if failed:
        print("Failed:", ", ".join(failed))
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::notice title=Charts::{len(out)} countries with charts, {len(no_store)} without a storefront, {len(failed)} failed. "
              + " | ".join("#1 in " + s for s in sample))

    if len(out) < MIN_EXPECTED:
        sys.exit(f"Only {len(out)} countries returned charts; Apple's feed may have changed. Leaving data/charts.json unchanged.")
    if dry:
        print("Dry run: nothing written.")
        return
    data = {
        "_about": "Most-played songs on Apple Music in each country's storefront, from Apple's public marketing feed. It reflects Apple Music listeners, which can be a small slice of people in some countries.",
        "source": "https://rss.applemarketingtools.com",
        "checked": datetime.date.today().isoformat(),
        "countries": out,
    }
    old_songs = {k: v.get("songs") for k, v in prev.items()}
    new_songs = {k: v.get("songs") for k, v in out.items()}
    if old_songs == new_songs and OUT.exists():
        print("Charts unchanged; nothing to write.")
        return
    OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {OUT.relative_to(ROOT)}.")


if __name__ == "__main__":
    main()
