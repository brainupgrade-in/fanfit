"""SPEC §9 day-1 data check against live Qloo. Uses the real pipeline functions, so parsing is exercised too.

Usage: QLOO_MODE=live uv run scripts/datacheck.py
"""
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from fanfit.pipeline import (  # noqa: E402
    Brief, Resolution, audience_demographics, find_partners, search_entities, search_tags,
)
from fanfit.qloo import QlooUnavailable, make_client  # noqa: E402

BRANDS = ["Liquid Death", "Patagonia", "Red Bull", "Glossier", "Oatly"]
TYPES = ["artist", "podcast", "tv_show", "person"]
q = make_client("live")


def raw_keys(path, params):
    body = q.get(path, params)
    res = body.get("results")
    first = (res[0] if isinstance(res, list) and res else
             next((v[0] for v in res.values() if isinstance(v, list) and v), None) if isinstance(res, dict) else None)
    return (list(res.keys()) if isinstance(res, dict) else type(res).__name__), (sorted(first.keys()) if isinstance(first, dict) else None)


print("== response shapes")
print("search  :", raw_keys("/search", {"query": "Patagonia", "types": ["urn:entity:brand"], "take": 3}))
print("tags    :", raw_keys("/v2/tags", {"filter.query": "coffee", "take": 3}))

print("\n== 1. brand coverage")
resolved = {}
for b in BRANDS:
    hits = search_entities(q, b, "urn:entity:brand", take=5)
    exact = [h for h in hits if h["name"].lower() == b.lower()]
    resolved[b] = (exact or hits or [None])[0]
    print(f"{b:14} hits={len(hits)} exact={bool(exact)} -> {resolved[b]['name'] if resolved[b] else '-'}")

print("\n== tags")
for t in ["cold brew", "trail running", "hot sauce", "skincare", "street food"]:
    print(f"{t:14}", [x["name"] for x in search_tags(q, t, take=3)])

print("\n== 2. partner types with a brand signal (count of results, take=20)")
brief = Brief(partner_types=TYPES)
rows = {}
for b, ent in resolved.items():
    if not ent:
        continue
    res = Resolution(brand=ent, brand_candidates=[], tags=[], unresolved=[])
    rows[b] = {t: find_partners(q, res, brief, t) for t in TYPES}
    print(f"{b:14}", {t: len(v) for t, v in rows[b].items()})

print("\n== 3. does the brand signal change the ranking? (mean top-10 Jaccard BETWEEN brands, per type)")
# Insights has no signal-free baseline (400: "at least one valid signal or filter is required"), so compare brands.
import itertools  # noqa: E402

for t in TYPES:
    tops = {b: {c["entity_id"] for c in by_type[t][:10]} for b, by_type in rows.items()}
    js = [len(tops[a] & tops[b]) / len(tops[a] | tops[b]) for a, b in itertools.combinations(tops, 2)]
    print(f"{t:8} mean J={sum(js) / len(js):.2f} (target < 0.5)")
for b, by_type in rows.items():
    print(f"{b:14} artists: {[c['name'] for c in by_type['artist'][:4]]}")

print("\n== 4. demographics (age affinity index, -1..1) for the first partner of each type")
b0 = next(iter(rows))
for t in TYPES:
    c = rows[b0][t][0]
    try:
        print(f"{t:8} {c['name'][:28]:28} {audience_demographics(q, c['entity_id']).get('age')}")
    except QlooUnavailable as e:
        print(f"{t:8} unavailable ({e})")
