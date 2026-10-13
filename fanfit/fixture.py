"""Synthetic Qloo stand-in for development before the API key arrives.

All entities in fixtures/world.json are fictional. Response shapes follow the Qloo API
reference and the official harness; field names still need confirming against live data.
"""
from __future__ import annotations

import json
from pathlib import Path

from fanfit.qloo import _wire, check_params

WORLD = Path(__file__).resolve().parent.parent / "fixtures" / "world.json"


class FixtureQlooClient:
    mode = "fixture"

    def __init__(self, world_path: Path = WORLD):
        w = json.loads(world_path.read_text())
        self.entities = {e["entity_id"]: e for e in w["entities"]}
        self.tags = {t["id"]: t for t in w["tags"]}
        self.calls: list[tuple[str, dict]] = []

    def get(self, path: str, params: dict) -> dict:
        check_params(path, params)
        self.calls.append((path, params))
        return getattr(self, "_" + path.strip("/").replace("/", "_"))(_wire(params))

    def _entity_out(self, e: dict, affinity: float | None = None) -> dict:
        out = {
            "entity_id": e["entity_id"],
            "name": e["name"],
            "types": [e["type"]],
            "popularity": e["popularity"],
            "tags": [{"id": t, "name": self.tags[t]["name"], "type": self.tags[t]["type"]} for t in e["tags"]],
        }
        if affinity is not None:
            out["query"] = {"affinity": round(affinity, 4)}
        return out

    def _search(self, p: dict) -> dict:
        q = p["query"].lower()
        types = set(p.get("types", "").split(",")) - {""}
        hits = [
            e for e in self.entities.values()
            if q in e["name"].lower() and (not types or e["type"] in types)
        ]
        return {"success": True, "results": [self._entity_out(e) for e in hits[: p.get("take", 10)]]}

    def _v2_tags(self, p: dict) -> dict:
        q = p["filter.query"].lower()
        hits = [t for t in self.tags.values() if q in t["name"].lower()]
        return {"success": True, "results": {"tags": [{"id": t["id"], "name": t["name"], "type": t["type"]} for t in hits]}}

    def _signal(self, p: dict) -> tuple[set, list[dict]]:
        ids = p.get("signal.interests.entities", [])
        ids = ids.split(",") if isinstance(ids, str) else ids
        tags = p.get("signal.interests.tags", [])
        tags = set(tags.split(",") if isinstance(tags, str) else tags)
        seeds = [self.entities[i] for i in ids if i in self.entities]
        for s in seeds:
            tags |= set(s["tags"])
        return tags, seeds

    def _affinity(self, e: dict, tags: set, p: dict) -> float:
        overlap = len(tags & set(e["tags"])) / max(1, len(tags | set(e["tags"])))
        score = 0.25 * e["popularity"] + 0.75 * overlap if tags else e["popularity"]
        age = p.get("signal.demographics.age")
        if age and age in e.get("demographics", {}).get("age", {}):
            score *= 1 + 0.3 * e["demographics"]["age"][age]  # index in -1..1
        return min(score, 1.0)

    def _v2_insights(self, p: dict) -> dict:
        t = p["filter.type"]
        tags, seeds = self._signal(p)
        if t == "urn:demographics":
            e = seeds[0]
            return {"success": True, "results": {"demographics": [
                {"entity_id": e["entity_id"], "query": e.get("demographics", {})}
            ]}}
        pool = [e for e in self.entities.values() if e["type"] == t and e not in seeds]
        scored = sorted(((self._affinity(e, tags, p), e) for e in pool), key=lambda x: -x[0])
        return {"success": True, "results": {"entities": [self._entity_out(e, a) for a, e in scored[: p.get("take", 20)]]}}
