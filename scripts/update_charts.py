#!/usr/bin/env python3
"""Refresh data/charts.json with each country's most-played songs on Apple Music.

Reads Apple's public marketing feed (no key needed), one request per country.
Countries without an Apple Music storefront are skipped. If a country's fetch
fails this time, its previous chart is kept.

Usage: python3 scripts/update_charts.py [--dry-run]
Uses only the Python standard library.
"""
import concurrent.futures
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

# Apple serves the same feed from two addresses; try the newer one first.
FEEDS = [
    "https://rss.marketingtools.apple.com/api/v2/{cc}/music/most-played/10/songs.json",
    "https://rss.applemarketingtools.com/api/v2/{cc}/music/most-played/10/songs.json",
]
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "charts.json"
COUNTRIES = ROOT / "data" / "countries.json"
# Apple's feed should answer for well over this many map countries; fewer means something broke.
MIN_EXPECTED = 40


HEADERS = {"User-Agent": "Mozilla/5.0 (HelloWorld charts; personal culture map)", "Accept": "application/json"}
working_feed = None   # whichever address answered first, reused for every other country


def fetch(cc):
    global working_feed
    urls = [working_feed] if working_feed else FEEDS
    last = None
    for url in urls:
        try:
            req = urllib.request.Request(url.format(cc=cc), headers=HEADERS)
            with urllib.request.urlopen(req, timeout=12) as r:
                data = json.loads(r.read())
            working_feed = url
            return data
        except urllib.error.HTTPError as e:
            if e.code == 404:
                working_feed = working_feed or url   # the server answered; the country just has no storefront
                raise
            last = e
        except Exception as e:
            last = e
    raise last


def main():
    dry = "--dry-run" in sys.argv
    countries = json.loads(COUNTRIES.read_text(encoding="utf-8"))
    old = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    prev = old.get("countries", {})
    out = {}
    no_store, failed = [], []

    # Try a few big storefronts first: if none answer, stop right away with the reason
    # instead of waiting out a timeout for every country.
    probe_errors = []
    for cc in ("us", "gb", "jp"):
        try:
            fetch(cc)
            break
        except Exception as e:
            probe_errors.append(f"{cc}: {type(e).__name__}: {e}")
    else:
        msg = "Apple's chart feed did not answer: " + " | ".join(probe_errors)
        if os.environ.get("GITHUB_ACTIONS"):
            print(f"::error title=Charts::{msg}")
        sys.exit(msg)

    def get_chart(cid):
        """Fetch one country, retrying slow or flaky requests. Returns (cid, outcome, payload)."""
        cc = ALPHA2.get(cid)
        err = None
        for attempt in range(3):
            try:
                return cid, "ok", fetch(cc).get("feed", {})
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return cid, "no_store", None   # no Apple Music storefront there
                err = f"HTTP {e.code}"
            except Exception as e:
                err = type(e).__name__
            time.sleep(1.5 * (attempt + 1))   # back off before retrying
        return cid, "failed", err

    # a few requests at a time: fast, but gentle on Apple's servers
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(get_chart, [c for c in sorted(countries) if ALPHA2.get(c)]))

    for cid, outcome, payload in results:
        if outcome == "no_store":
            no_store.append(countries[cid]["name"])
            continue
        if outcome == "failed":
            failed.append(f"{countries[cid]['name']} ({payload})")
            if cid in prev:
                out[cid] = prev[cid]   # keep the last good chart
            continue
        songs = []
        for r in payload.get("results", [])[:10]:
            if r.get("name") and r.get("url"):
                songs.append({"name": r["name"], "artist": r.get("artistName", ""), "url": r["url"]})
        if songs:
            updated = (payload.get("updated") or "")[:10] or datetime.date.today().isoformat()
            out[cid] = {"updated": updated, "songs": songs}

    print(f"Charts for {len(out)} countries; no Apple Music storefront: {len(no_store)}; failed this run: {len(failed)}")
    sample = [f"{countries[c]['name']}: {out[c]['songs'][0]['name']} by {out[c]['songs'][0]['artist']}" for c in ("620", "484", "392") if c in out]
    for line in sample:
        print("  #1 in", line)
    if failed:
        print("Failed:", ", ".join(failed))
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::notice title=Charts::Feed: {working_feed.split('/api')[0] if working_feed else 'none'}. {len(out)} countries with charts, {len(no_store)} without a storefront, {len(failed)} failed. "
              + " | ".join("#1 in " + s for s in sample)
              + (f" | Failed: {', '.join(failed[:12])}" + (" ..." if len(failed) > 12 else "") if failed else ""))

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
