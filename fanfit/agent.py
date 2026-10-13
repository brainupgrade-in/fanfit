"""LLM parts: a tool-calling agent that turns a free-text brief into confirmed Qloo ids,
and a claims writer whose output is checked by grounding.validate_claims."""
from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Protocol

import httpx

from fanfit.grounding import clean_framing, foreign_names_for, validate_claims
from fanfit.pipeline import Brief, Resolution, search_entities, search_tags
from fanfit.qloo import QlooClient

MAX_TOOL_CALLS = 12


class LLM(Protocol):
    def chat(self, messages: list[dict], tools: list[dict] | None = None, json_mode: bool = False) -> dict: ...


class OpenAICompatLLM:
    """Any OpenAI-compatible /chat/completions endpoint (Nebius Token Factory, LiteLLM)."""

    def __init__(self, base_url: str, api_key: str, model: str):
        self.model = model
        self.http = httpx.Client(base_url=base_url.rstrip("/"), headers={"Authorization": f"Bearer {api_key}"}, timeout=60)

    @classmethod
    def from_env(cls) -> "OpenAICompatLLM | None":
        keys = ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL")
        if not all(os.environ.get(k) for k in keys):
            return None
        return cls(*(os.environ[k] for k in keys))

    def chat(self, messages, tools=None, json_mode=False):
        body = {"model": self.model, "messages": messages, "temperature": 0.2}
        if tools:
            body["tools"] = tools
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        r = self.http.post("/chat/completions", json=body)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]


def _fn(name, desc, props, required):
    return {"type": "function", "function": {"name": name, "description": desc,
            "parameters": {"type": "object", "properties": props, "required": required}}}


TOOLS = [
    _fn("search_brand", "Look up a brand in Qloo by name. Pass a short brand name only.",
        {"term": {"type": "string", "maxLength": 40}}, ["term"]),
    _fn("search_tags", "Look up Qloo taste tags for a 1-3 word category or vibe (e.g. 'cold brew').",
        {"term": {"type": "string", "maxLength": 40}}, ["term"]),
    _fn("finish", "Return the resolved brief once the brand and tags are found.", {
        "brand_entity_id": {"type": ["string", "null"], "description": "entity_id from search_brand, or null if not in Qloo"},
        "tag_ids": {"type": "array", "items": {"type": "string"}, "description": "ids from search_tags, max 3"},
        "age": {"type": ["string", "null"], "enum": ["24_and_younger", "25_to_29", "30_to_34", "35_to_44", "45_to_54", "55_and_older", None]},
        "gender": {"type": ["string", "null"], "enum": ["male", "female", None]},
        "market": {"type": ["string", "null"], "description": "target city or region, short"},
        "partner_types": {"type": "array", "items": {"type": "string", "enum": ["artist", "podcast", "tv_show", "person"]}},
    }, ["brand_entity_id", "tag_ids", "partner_types"]),
]

RESOLVE_SYSTEM = """You turn a sponsorship campaign brief into Qloo ids.
Use search_brand for the brand name and search_tags for up to 3 short category or vibe words.
Only ever pass short lookup terms (max 40 chars) to tools, never the whole brief, and never a private person's name.
If the brand is not found, try one shorter variant, then continue with tags only.
If several brands match, pick the exact name match.
Put the target city or region in finish.market; it is NOT a taste tag, so never search it with search_tags.
Then call finish exactly once."""


def resolve_with_agent(text: str, qloo: QlooClient, llm: LLM, trace: list[str]) -> tuple[Brief, Resolution]:
    messages = [{"role": "system", "content": RESOLVE_SYSTEM}, {"role": "user", "content": text}]
    seen_brands: dict[str, dict] = {}
    seen_tags: dict[str, dict] = {}
    unresolved: list[str] = []
    for _ in range(MAX_TOOL_CALLS):
        msg = llm.chat(messages, tools=TOOLS)
        messages.append(msg)
        calls = msg.get("tool_calls") or []
        if not calls:
            messages.append({"role": "user", "content": "Call a tool. Finish with the finish tool."})
            continue
        for call in calls:
            name = call["function"]["name"]
            args = json.loads(call["function"]["arguments"] or "{}")
            if name == "finish":
                return _finish(args, seen_brands, seen_tags, unresolved)
            term = str(args.get("term", ""))[:40]
            if name == "search_brand":
                result = search_entities(qloo, term, "urn:entity:brand")
                seen_brands.update({e["entity_id"]: e for e in result})
            else:
                result = search_tags(qloo, term, take=3)
                seen_tags.update({t["id"]: t for t in result})
            if not result:
                unresolved.append(term)
            what = "brand" if name == "search_brand" else "taste tag"
            found = f"{len(result)} match" + ("es" if len(result) != 1 else "") if result else "not found"
            trace.append(f"Agent looked up {what} “{term}” in Qloo: {found}")
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result)})
    raise RuntimeError("agent did not finish within the tool-call budget")


def _finish(args, seen_brands, seen_tags, unresolved) -> tuple[Brief, Resolution]:
    """Only accept ids the agent actually saw from Qloo."""
    brand = seen_brands.get(args.get("brand_entity_id") or "")
    tags = [seen_tags[t] for t in (args.get("tag_ids") or [])[:3] if t in seen_tags]
    brief = Brief(
        brand=brand["name"] if brand else None,
        category_terms=[t["name"] for t in tags],
        age=args.get("age"), gender=args.get("gender"), market=args.get("market"),
        partner_types=args.get("partner_types") or ["artist", "podcast"],
    ).clean()
    return brief, Resolution(brand=brand, brand_candidates=list(seen_brands.values()), tags=tags, unresolved=unresolved)


EVIDENCE_GUIDE = """How to read the evidence (all from Qloo):
- affinity: Qloo's 0-1 score for how strongly the partner's audience matches the brand's taste signal. rank = position in this shortlist.
- taste:*: Qloo's taste tags for the partner's audience (what those fans are into). The brand itself has no tags, so do NOT
  call them "shared"; say "their audience is into indie folk", and you may say why that suits the brand.
- demo:<band>: an age affinity INDEX from -1 to 1 for that band (positive = over-indexes, negative = under-indexes).
  It is NOT a share or percentage of the audience, and it is the partner's overall profile, NOT specific to the market.
  Say "over-indexes with 25-29 year olds (+0.70)", never "70% of listeners" or "in London it over-indexes".
- market: the ranking (affinity) was computed with a location signal for this market."""

CLAIMS_SYSTEM = """You explain why a sponsorship partner fits a brand, using ONLY the evidence given.
Return JSON: {"claims": [{"text": "...", "evidence_ids": ["<key from evidence>"]}]}.
2-4 claims, one sentence each. Every claim must cite at least one evidence key.
Do not mention any fact, partner, tag, number or place that is not in the evidence.
If you call something strong, high or top, quote its value (e.g. "affinity 0.42", "18% of fans").
The partner is the given partner_type (an artist, podcast, show or creator), NOT a brand: refer to it by name.
Write for a brand marketer: plain words, numbers rounded to 2 decimals, shares as percentages.
""" + EVIDENCE_GUIDE


CREATOR_EVIDENCE_GUIDE = """How to read the evidence (all from Qloo):
- affinity: Qloo's 0-1 score for how strongly the brand's customers match the creator's audience. rank = position in this shortlist.
- life:*: Qloo's aspirational-lifestyle themes for the brand's customers. identity: Qloo's one-line description of them.
  These describe the brand's customers, not the creator's fans; say "Whoop's customers lean into Peak Performance".
- demo:<band>: an age affinity INDEX from -1 to 1 for the brand's customers in that band (positive = over-indexes).
  It is NOT a share or percentage, and it is the brand's overall profile, NOT specific to the market.
- market: the ranking (affinity) was computed with a location signal for this market."""

CREATOR_CLAIMS_SYSTEM = """You explain to a creator (an artist, podcast, show or person) why a brand is a good sponsor to pitch,
using ONLY the evidence given. Return JSON: {"claims": [{"text": "...", "evidence_ids": ["<key from evidence>"]}]}.
2-4 claims, one sentence each. Every claim must cite at least one evidence key.
Do not mention any fact, brand, theme, number or place that is not in the evidence.
If you call something strong, high or top, quote its value (e.g. "affinity 0.93").
Refer to the brand and the creator by name. Plain words, numbers rounded to 2 decimals.
Say nothing about the creator's content, topics or style: the evidence describes the brand's customers only.
""" + CREATOR_EVIDENCE_GUIDE


def _to_brand(card: dict) -> bool:
    """Reverse mode: the card's partner is a brand, and the subject of the brief is a creator."""
    return card["partner"]["type"] == "urn:entity:brand"


def write_claims(card: dict, cards: list[dict], brand_label: str, llm: LLM) -> list[dict]:
    if _to_brand(card):
        system, payload = CREATOR_CLAIMS_SYSTEM, {"creator": brand_label, "brand": card["partner"]["name"], "evidence": card["evidence"]}
    else:
        system, payload = CLAIMS_SYSTEM, {"brand": brand_label, "partner": card["partner"]["name"],
                                          "partner_type": card["partner"]["type"].split(":")[-1], "evidence": card["evidence"]}
    msg = llm.chat([{"role": "system", "content": system}, {"role": "user", "content": json.dumps(payload)}], json_mode=True)
    try:
        claims = json.loads(msg.get("content") or "{}").get("claims", [])
    except json.JSONDecodeError:
        return []
    return validate_claims(card, claims, foreign_names_for(card, cards))


def add_claims(cards: list[dict], brand_label: str, llm: LLM) -> bool:
    """Fill card["claims"] for all cards in parallel. Returns False if the LLM failed (cards keep evidence only)."""
    def one(card):
        card["claims"] = write_claims(card, cards, brand_label, llm)

    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(one, cards))
    except Exception:
        for c in cards:
            c["claims"] = []
        return False
    return True


BASELINE_SYSTEM = """You are a sponsorship strategist. Suggest real sponsorship partners for the brief.
Return JSON: {"partners": [{"name": "...", "type": "artist|podcast|tv_show|person", "reason": "one short sentence"}]}.
Suggest up to 8, only of the requested types. Use exact, well-known names."""


CREATOR_BASELINE_SYSTEM = """You are a talent manager. Suggest real brands that would sponsor this creator.
Return JSON: {"partners": [{"name": "...", "type": "brand", "reason": "one short sentence"}]}.
Suggest up to 8 brands. Use exact, well-known brand names."""


def llm_only_partners(brand_label: str, brief: Brief, llm: LLM) -> list[dict]:
    """The AI-alone baseline for the comparison panel: same brief and model, no Qloo tools."""
    b = brief.clean()
    if b.subject_type != "brand":
        system, ask = CREATOR_BASELINE_SYSTEM, {"creator": brand_label, "creator_type": b.subject_type, "fans_age_band": b.age, "market": b.market}
    else:
        system, ask = BASELINE_SYSTEM, {"brand": brand_label, "categories": b.category_terms, "age_band": b.age, "market": b.market,
                                        "partner_types": b.partner_types}
    msg = llm.chat([{"role": "system", "content": system}, {"role": "user", "content": json.dumps(ask)}], json_mode=True)
    try:
        raw = json.loads(msg.get("content") or "{}").get("partners", [])
    except json.JSONDecodeError:
        return []
    out = []
    for p in raw[:8]:
        name, ptype = str(p.get("name", "")).strip(), p.get("type")
        if name and len(name) <= 40 and ptype in b.partner_types:
            out.append({"name": name, "type": ptype, "reason": str(p.get("reason", ""))[:200]})
    return out


PITCH_SYSTEM = """You draft a short sponsorship outreach email from a brand to a partner (artist, podcast, show or creator).
Use ONLY the evidence given for facts. Return JSON:
{"subject": "...", "opening": "one friendly sentence, no numbers",
 "points": [{"text": "one sentence", "evidence_ids": ["<key from evidence>"]}],
 "ask": "one sentence proposing a next step"}
2-4 points; every point cites at least one evidence key and quotes its value when it says strong/high/top.
Address the partner by name. Never mention other partners, invented numbers, prices or deliverables.
Don't claim personal experience you can't know (e.g. "I've been enjoying your podcast"); open with why you're writing.
""" + EVIDENCE_GUIDE


CREATOR_PITCH_SYSTEM = """You draft a short sponsorship outreach email from a creator (an artist, podcast, show or person) to a brand.
Use ONLY the evidence given for facts. Return JSON:
{"subject": "...", "opening": "one friendly sentence, no numbers",
 "points": [{"text": "one sentence", "evidence_ids": ["<key from evidence>"]}],
 "ask": "one sentence proposing a next step"}
2-4 points; every point cites at least one evidence key and quotes its value when it says strong/high/top.
Address the brand by name. Never mention other brands, invented numbers, prices, follower counts or deliverables.
Don't claim personal experience you can't know (e.g. "I've been enjoying your products"), and don't describe the creator's content;
open with why you're writing.
""" + CREATOR_EVIDENCE_GUIDE


def supportive_evidence(card: dict) -> dict:
    """The subset of a card's evidence that argues FOR the partnership. The card shows everything; a pitch shouldn't
    sell an under-indexed age band."""
    keep = {}
    for k, v in card["evidence"].items():
        if k.startswith("demo:") and v["value"] < 0.2:  # only clear over-indexing is a selling point
            continue
        keep[k] = v
    return keep


def draft_pitch(card: dict, cards: list[dict], brand_label: str, llm: LLM, foreign: set[str] | None = None) -> dict | None:
    """Outreach email whose every fact is a validated, evidence-cited point. None if nothing grounded survives."""
    partner = card["partner"]["name"]
    foreign = foreign if foreign is not None else foreign_names_for(card, cards)
    card = {**card, "evidence": supportive_evidence(card)}
    if _to_brand(card):
        system, payload = CREATOR_PITCH_SYSTEM, {"creator": brand_label, "brand": partner, "evidence": card["evidence"]}
    else:
        system, payload = PITCH_SYSTEM, {"brand": brand_label, "partner": partner, "partner_type": card["partner"]["type"].split(":")[-1],
                                         "evidence": card["evidence"]}
    msg = llm.chat([{"role": "system", "content": system}, {"role": "user", "content": json.dumps(payload)}], json_mode=True)
    try:
        raw = json.loads(msg.get("content") or "{}")
    except json.JSONDecodeError:
        return None
    points = validate_claims(card, raw.get("points") or [], foreign)
    if not points:
        return None
    return {
        "subject": clean_framing(raw.get("subject"), f"Partnership idea: {brand_label} x {partner}", foreign),
        "opening": clean_framing(raw.get("opening"), f"Hi {partner} team,", foreign),
        "points": points,
        "ask": clean_framing(raw.get("ask"), "Would you be open to a short call to explore a partnership?", foreign, allow_counts=True),
    }
