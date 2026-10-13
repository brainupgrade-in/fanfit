"""LLM parts: a tool-calling agent that turns a free-text brief into confirmed Qloo ids,
and a claims writer whose output is checked by grounding.validate_claims."""
from __future__ import annotations

import json
import os
from typing import Protocol

import httpx

from fanfit.grounding import foreign_names_for, validate_claims
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
            trace.append(f"agent: {name}({term!r}) → {len(result)} match(es)")
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


CLAIMS_SYSTEM = """You explain why a sponsorship partner fits a brand, using ONLY the evidence given.
Return JSON: {"claims": [{"text": "...", "evidence_ids": ["<key from evidence>"]}]}.
2-4 claims, one sentence each. Every claim must cite at least one evidence key.
Do not mention any fact, partner, tag, number or place that is not in the evidence."""


def write_claims(card: dict, cards: list[dict], brand_label: str, llm: LLM) -> list[dict]:
    payload = {"brand": brand_label, "partner": card["partner"]["name"], "evidence": card["evidence"]}
    msg = llm.chat([{"role": "system", "content": CLAIMS_SYSTEM}, {"role": "user", "content": json.dumps(payload)}], json_mode=True)
    try:
        claims = json.loads(msg.get("content") or "{}").get("claims", [])
    except json.JSONDecodeError:
        return []
    return validate_claims(card, claims, foreign_names_for(card, cards))
