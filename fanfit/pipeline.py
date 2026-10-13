"""Brief → resolved Qloo ids → ranked partner shortlist with evidence cards.

Response parsing lives here only, so confirming field names against live Qloo touches one file.
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from fanfit.qloo import AGE_BANDS, GENDERS, TEXT_MAX, QlooBadRequest, QlooClient, QlooUnavailable

PARTNER_TYPES = {"artist", "podcast", "tv_show", "person"}
SUBJECT_TYPES = {"brand"} | PARTNER_TYPES  # who the brief is for; anything but "brand" is reverse mode (creator → brands)
MAX_CARDS = 8


@dataclass
class Brief:
    brand: str | None = None
    category_terms: list[str] = field(default_factory=list)
    age: str | None = None
    gender: str | None = None
    market: str | None = None
    partner_types: list[str] = field(default_factory=lambda: ["artist", "podcast"])
    subject_type: str = "brand"  # what `brand` names; a creator type means "find brands for this creator"

    def clean(self) -> "Brief":
        """Clamp to what may be sent to Qloo (SPEC §8)."""
        short = lambda s: s.strip()[:TEXT_MAX] if s and s.strip() else None
        subject = self.subject_type if self.subject_type in SUBJECT_TYPES else "brand"
        return Brief(
            subject_type=subject,
            brand=short(self.brand),
            category_terms=[t for t in (short(t) for t in self.category_terms[:3]) if t],
            age=self.age if self.age in AGE_BANDS else None,
            gender=self.gender if self.gender in GENDERS else None,
            market=short(self.market),
            partner_types=["brand"] if subject != "brand" else [t for t in self.partner_types if t in PARTNER_TYPES | {"brand"}] or ["artist"],
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
    candidates = search_entities(qloo, brief.brand, f"urn:entity:{brief.subject_type}") if brief.brand else []
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
    if brief.market:
        p["signal.location.query"] = brief.market  # live check: re-ranks partners for that market
    return p


# Qloo tags that say nothing about taste (live data, 2026-10-13).
_GENERIC_TAGS = {"podcasts", "podcast", "music", "tv", "television", "person", "people"}


def _taste_tags(e: dict, n: int = 6) -> list[dict]:
    out, seen = [], set()
    for t in e.get("tags", []):
        name = (t.get("name") or "").strip()
        if not t.get("id") or len(name) < 3 or name.isdigit() or name.lower() in _GENERIC_TAGS or name.lower() in seen:
            continue
        seen.add(name.lower())
        out.append({"id": t["id"], "name": name})
    return out[:n]


def _as_list(v) -> list:
    return v if isinstance(v, list) else [v] if v else []


def _brand_extras(e: dict) -> dict:
    """Brand results carry Qloo-written audience properties (live, 2026-10-13); their tags are mostly Wikipedia
    categories ("1920 establishments in …"), so lifestyle themes stand in for taste tags."""
    props = e.get("properties") or {}
    life = list(dict.fromkeys(str(x).strip() for x in _as_list(props.get("aspirational_lifestyle")) if str(x).strip()))
    identity = props.get("audience_identity")
    return {"tags": [], "lifestyle": life[:5], "identity": identity.strip() if isinstance(identity, str) and identity.strip() else None}


def _nonprofit(e: dict) -> bool:
    return "Nonprofit" in _as_list((e.get("properties") or {}).get("business_model"))


def find_partners(qloo: QlooClient, res: Resolution, brief: Brief, ptype: str, take: int = 20) -> list[dict]:
    params = {"filter.type": f"urn:entity:{ptype}", **_signal(res, brief), "take": take}
    out = []
    for e in qloo.get("/v2/insights", params).get("results", {}).get("entities", []):
        if ptype == "brand" and _nonprofit(e):  # charities show up as brands but don't buy sponsorships
            continue
        c = {**_entity(e), "type": f"urn:entity:{ptype}", "affinity": _affinity(e), "popularity": e.get("popularity"),
             "tags": _taste_tags(e)}
        out.append({**c, **_brand_extras(e)} if ptype == "brand" else c)
    return out


def audience_demographics(qloo: QlooClient, entity_id: str) -> dict:
    """{"age": {band: index}, "gender": {...}}. Indices run -1..1 (over/under-indexing), NOT audience shares."""
    rows = qloo.get("/v2/insights", {"filter.type": "urn:demographics", "signal.interests.entities": [entity_id]}).get("results", {}).get("demographics", [])
    return (rows[0].get("query") or {}) if rows else {}


def build_card(rank: int, c: dict, brief: Brief, demo: dict) -> dict:
    """Every fact on the card is keyed by an evidence id; claims may only cite these keys."""
    ev = {"affinity": {"label": "Qloo affinity with the brand's taste signal", "value": c["affinity"], "rank": rank}}
    for t in c["tags"]:
        ev[f"taste:{t['id']}"] = {"label": "Qloo taste tag for this partner's audience", "value": t["name"]}
    for i, v in enumerate(c.get("lifestyle") or [], 1):
        ev[f"life:{i}"] = {"label": "Qloo aspirational-lifestyle theme for this brand's customers", "value": v}
    if c.get("identity"):
        ev["identity"] = {"label": "Qloo's description of this brand's audience", "value": c["identity"]}
    ages = demo.get("age") or {}
    band = brief.age if brief.age in ages else (max(ages, key=ages.get) if ages else None)
    if band:
        ev[f"demo:{band}"] = {"label": "Age affinity index, -1 to 1 (over/under-indexing, not a share)",
                              "value": round(ages[band], 2), "band": band, "target": band == brief.age}
    if brief.market:
        ev["market"] = {"label": "Ranked with a Qloo location signal for", "value": brief.market}
    return {"rank": rank, "partner": {k: c[k] for k in ("entity_id", "name", "type")}, "affinity": c["affinity"], "evidence": ev, "claims": []}


def rank_pool(res: Resolution, brief: Brief, qloo: QlooClient, trace: list[str] | None = None) -> list[dict]:
    """All candidates for the brief across partner types, best Qloo affinity first."""
    brief = brief.clean()
    trace = trace if trace is not None else []
    pool = []
    with ThreadPoolExecutor(max_workers=len(brief.partner_types)) as ex:
        for ptype, found in zip(brief.partner_types, ex.map(lambda t: find_partners(qloo, res, brief, t), brief.partner_types)):
            trace.append(f"Qloo insights: {len(found)} {ptype} candidates")
            pool += found
    return sorted((c for c in pool if c["affinity"] is not None), key=lambda c: -c["affinity"])


def shortlist(res: Resolution, brief: Brief, qloo: QlooClient, trace: list[str] | None = None) -> list[dict]:
    brief = brief.clean()
    trace = trace if trace is not None else []
    try:
        pool = rank_pool(res, brief, qloo, trace)[:MAX_CARDS]
    except QlooBadRequest:
        if not brief.market:
            raise
        trace.append(f"Qloo didn't recognise the market “{brief.market}”, so partners are ranked without a location signal")
        brief = Brief(**{**brief.__dict__, "market": None})
        pool = rank_pool(res, brief, qloo, trace)[:MAX_CARDS]
    def demo_for(c: dict) -> dict:
        try:  # optional enrichment: a card still ships with affinity + taste tags if this fails
            return audience_demographics(qloo, c["entity_id"])
        except QlooUnavailable as e:
            trace.append(f"enrichment skipped for {c['name']}: {e}")
            return {}

    with ThreadPoolExecutor(max_workers=MAX_CARDS) as ex:
        demos = list(ex.map(demo_for, pool))
    cards = [build_card(i, c, brief, d) for i, (c, d) in enumerate(zip(pool, demos), 1)]
    trace.append(f"Built {len(cards)} fit cards")
    return cards


def _norm(name: str) -> str:
    n = re.sub(r"[^a-z0-9 ]", " ", name.lower())
    n = re.sub(r"\s+", " ", n).strip()
    return n[4:] if n.startswith("the ") else n


def same_entity_name(a: str, b: str) -> bool:
    """Exact after normalising, or one name is the other plus a suffix ("How I Built This" ~ "… with Guy Raz")."""
    x, y = _norm(a), _norm(b)
    if x == y:
        return True
    short, long_ = sorted((x, y), key=len)
    return len(short) >= 8 and long_.startswith(short + " ")


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
        hits = search_entities(qloo, sug["name"][:TEXT_MAX], f"urn:entity:{sug['type']}", take=5)
        hit = next((h for h in hits if same_entity_name(h["name"], sug["name"])), None)
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
