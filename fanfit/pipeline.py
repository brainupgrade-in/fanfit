"""Brief → resolved Qloo ids → ranked partner shortlist with evidence cards.

Response parsing lives here only, so confirming field names against live Qloo touches one file.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from fanfit.qloo import AGE_BANDS, GENDERS, TEXT_MAX, QlooClient, QlooUnavailable

PARTNER_TYPES = {"artist", "podcast", "tv_show", "person"}
MAX_CARDS = 8


@dataclass
class Brief:
    brand: str | None = None
    category_terms: list[str] = field(default_factory=list)
    age: str | None = None
    gender: str | None = None
    market: str | None = None
    partner_types: list[str] = field(default_factory=lambda: ["artist", "podcast"])

    def clean(self) -> "Brief":
        """Clamp to what may be sent to Qloo (SPEC §8)."""
        short = lambda s: s.strip()[:TEXT_MAX] if s and s.strip() else None
        return Brief(
            brand=short(self.brand),
            category_terms=[t for t in (short(t) for t in self.category_terms[:3]) if t],
            age=self.age if self.age in AGE_BANDS else None,
            gender=self.gender if self.gender in GENDERS else None,
            market=short(self.market),
            partner_types=[t for t in self.partner_types if t in PARTNER_TYPES] or ["artist"],
        )


@dataclass
class Resolution:
    brand: dict | None
    brand_candidates: list[dict]
    tags: list[dict]
    unresolved: list[str]


def _entity(e: dict) -> dict:
    types = e.get("types") or [e.get("type")]
    return {"entity_id": e["entity_id"], "name": e["name"], "type": types[0]}


def _affinity(e: dict) -> float | None:
    a = e.get("affinity")
    return a if a is not None else (e.get("query") or {}).get("affinity")


def search_entities(qloo: QlooClient, term: str, etype: str, take: int = 5) -> list[dict]:
    body = qloo.get("/search", {"query": term, "types": [etype], "take": take})
    return [_entity(e) for e in body.get("results", [])]


def search_tags(qloo: QlooClient, term: str, take: int = 5) -> list[dict]:
    body = qloo.get("/v2/tags", {"filter.query": term, "take": take})
    res = body.get("results", {})
    tags = res.get("tags", []) if isinstance(res, dict) else res
    return [{"id": t["id"], "name": t["name"]} for t in tags[:take]]


def resolve(brief: Brief, qloo: QlooClient) -> Resolution:
    brief = brief.clean()
    unresolved = []
    candidates = search_entities(qloo, brief.brand, "urn:entity:brand") if brief.brand else []
    if brief.brand and not candidates:
        unresolved.append(brief.brand)
    exact = [c for c in candidates if c["name"].lower() == brief.brand.lower()] if brief.brand else []
    tags = []
    for term in brief.category_terms:
        found = search_tags(qloo, term, take=1)
        tags += found
        if not found:
            unresolved.append(term)
    return Resolution(
        brand=exact[0] if exact else (candidates[0] if len(candidates) == 1 else None),
        brand_candidates=candidates,
        tags=tags,
        unresolved=unresolved,
    )


def _signal(res: Resolution, brief: Brief) -> dict:
    p = {}
    if res.brand:
        p["signal.interests.entities"] = [res.brand["entity_id"]]
    if res.tags:
        p["signal.interests.tags"] = [t["id"] for t in res.tags]
        p["operator.signal.interests.tags"] = "union"
    if brief.age:
        p["signal.demographics.age"] = brief.age
    if brief.gender:
        p["signal.demographics.gender"] = brief.gender
    return p


def find_partners(qloo: QlooClient, res: Resolution, brief: Brief, ptype: str, take: int = 20) -> list[dict]:
    params = {"filter.type": f"urn:entity:{ptype}", **_signal(res, brief), "feature.explainability": True, "take": take}
    out = []
    for e in qloo.get("/v2/insights", params).get("results", {}).get("entities", []):
        shared = ((e.get("query") or {}).get("explainability") or {}).get("signal.interests.tags", [])
        out.append({
            **_entity(e),
            "type": f"urn:entity:{ptype}",
            "affinity": _affinity(e),
            "popularity": e.get("popularity"),
            "shared_tags": [{"id": t.get("tag_id") or t.get("id"), "name": t["name"]} for t in shared],
            "tags": [{"id": t["id"], "name": t["name"]} for t in e.get("tags", [])],
        })
    return out


def audience_geo(qloo: QlooClient, entity_id: str, market: str | None, take: int = 5) -> list[dict]:
    p = {"filter.type": "urn:heatmap", "signal.interests.entities": [entity_id], "take": take}
    if market:
        p["filter.location.query"] = market
    rows = qloo.get("/v2/insights", p).get("results", {}).get("heatmap", [])
    rows = sorted(rows, key=lambda r: -(r.get("query") or {}).get("affinity", 0))
    return [{"region": r["location"].get("name") or r["location"].get("geohash"), "affinity": r["query"]["affinity"]} for r in rows[:take]]


def audience_demographics(qloo: QlooClient, entity_id: str) -> dict:
    rows = qloo.get("/v2/insights", {"filter.type": "urn:demographics", "signal.interests.entities": [entity_id]}).get("results", {}).get("demographics", [])
    return (rows[0].get("query") or {}) if rows else {}


def trend(qloo: QlooClient, entity_id: str, etype: str, today: date | None = None) -> list[dict]:
    today = today or date.today()
    p = {
        "filter.type": etype,
        "signal.interests.entities": [entity_id],
        "filter.start_date": (today - timedelta(days=180)).isoformat(),
        "filter.end_date": today.isoformat(),
    }
    return qloo.get("/v2/trending", p).get("results", {}).get("trending", [])


def build_card(rank: int, c: dict, brief: Brief, geo: list[dict], demo: dict, trend_pts: list[dict]) -> dict:
    """Every fact on the card is keyed by an evidence id; claims may only cite these keys."""
    ev = {"affinity": {"label": "Qloo affinity", "value": c["affinity"], "rank": rank}}
    for t in c["shared_tags"]:
        ev[f"tag:{t['id']}"] = {"label": "Shared taste tag", "value": t["name"]}
    for g in geo:
        ev[f"geo:{g['region']}"] = {"label": "Regional taste affinity (not where fans live)", "value": g["region"], "affinity": g["affinity"]}
    ages = demo.get("age") or {}
    if brief.age and brief.age in ages:
        ev[f"demo:{brief.age}"] = {"label": "Share in target age band", "value": ages[brief.age]}
    if trend_pts:
        deltas = [p.get("population_rank_delta", 0) for p in trend_pts]
        ev["trend"] = {"label": "Rank change, last 6 months", "value": sum(deltas)}
    return {"rank": rank, "partner": {k: c[k] for k in ("entity_id", "name", "type")}, "affinity": c["affinity"], "evidence": ev, "claims": []}


def rank_pool(res: Resolution, brief: Brief, qloo: QlooClient, trace: list[str] | None = None) -> list[dict]:
    """All candidates for the brief across partner types, best Qloo affinity first."""
    brief = brief.clean()
    trace = trace if trace is not None else []
    pool = []
    for ptype in brief.partner_types:
        found = find_partners(qloo, res, brief, ptype)
        trace.append(f"Qloo insights: {len(found)} {ptype} candidates")
        pool += found
    return sorted((c for c in pool if c["affinity"] is not None), key=lambda c: -c["affinity"])


def shortlist(res: Resolution, brief: Brief, qloo: QlooClient, trace: list[str] | None = None) -> list[dict]:
    brief = brief.clean()
    trace = trace if trace is not None else []
    pool = rank_pool(res, brief, qloo, trace)[:MAX_CARDS]
    cards = []
    for i, c in enumerate(pool, 1):
        geo, demo, pts = [], {}, []
        try:  # optional enrichments: a card still ships with affinity + tags if these fail
            geo = audience_geo(qloo, c["entity_id"], brief.market)
            demo = audience_demographics(qloo, c["entity_id"])
            pts = trend(qloo, c["entity_id"], c["type"])
        except QlooUnavailable as e:
            trace.append(f"enrichment skipped for {c['name']}: {e}")
        cards.append(build_card(i, c, brief, geo, demo, pts))
    trace.append(f"Built {len(cards)} fit cards")
    return cards


def compare_with_qloo(qloo: QlooClient, suggestions: list[dict], pool: list[dict], cards: list[dict]) -> dict:
    """Check AI-alone partner picks against Qloo (SPEC §5.4).

    Status per suggestion: shortlisted (in FanFit's cards), low (Qloo ranks it below the shortlist),
    not_ranked (in Qloo but not a candidate for this brief), not_found (Qloo has no such entity).
    """
    rank_of = {c["entity_id"]: i for i, c in enumerate(pool, 1)}
    by_id = {c["entity_id"]: c for c in pool}
    matched_ids = set()
    out = []
    for sug in suggestions:
        hits = search_entities(qloo, sug["name"][:TEXT_MAX], f"urn:entity:{sug['type']}", take=3)
        hit = next((h for h in hits if h["name"].lower() == sug["name"].lower()), None)
        if not hit:
            q = {"status": "not_found"}
        elif hit["entity_id"] in rank_of:
            matched_ids.add(hit["entity_id"])
            r = rank_of[hit["entity_id"]]
            q = {"status": "shortlisted" if r <= len(cards) else "low", "rank": r, "of": len(pool),
                 "affinity": by_id[hit["entity_id"]]["affinity"]}
        else:
            q = {"status": "not_ranked"}
        out.append({**sug, "qloo": q})
    qloo_only = [{"name": c["partner"]["name"], "type": c["partner"]["type"], "rank": c["rank"], "affinity": c["affinity"]}
                 for c in cards if c["partner"]["entity_id"] not in matched_ids]
    return {"llm_only": out, "qloo_only": qloo_only}
