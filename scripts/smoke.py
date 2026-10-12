"""Smoke test for the Qloo hackathon API: search an entity, then ask Insights for recommendations.

Usage: uv run scripts/smoke.py ["Agatha Christie"]
"""
import os
import sys

import httpx
from dotenv import load_dotenv

load_dotenv()
BASE = "https://hackathon.api.qloo.com"  # hackathon keys only work here, not api.qloo.com

key = os.environ.get("QLOO_API_KEY")
if not key:
    sys.exit("QLOO_API_KEY not set (put it in .env)")

client = httpx.Client(base_url=BASE, headers={"X-Api-Key": key}, timeout=30)
query = sys.argv[1] if len(sys.argv) > 1 else "Agatha Christie"

r = client.get("/search", params={"query": query, "take": 3})
r.raise_for_status()
results = r.json().get("results", [])
for e in results:
    print(f"search: {e.get('name')} | {e.get('entity_id')} | {e.get('types')}")
if not results:
    sys.exit(f"no search results for {query!r}")

r = client.get(
    "/v2/insights",
    params={
        "filter.type": "urn:entity:movie",
        "signal.interests.entities": results[0]["entity_id"],
        "take": 5,
    },
)
r.raise_for_status()
for e in r.json().get("results", {}).get("entities", []):
    print(f"insight: {e.get('name')} | affinity={e.get('query', {}).get('affinity')}")
