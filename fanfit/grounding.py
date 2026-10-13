"""Keep the LLM's "why this fit" claims tied to evidence on the card (SPEC §5.3)."""
from __future__ import annotations

import re

# "strong", "highly", "top" etc. are only allowed next to a measured value (0.42 or 18%), not a bare age band.
_STRENGTH = re.compile(r"\b(strong(ly)?|high(ly|er|est)?|very|top|best|most|significant(ly)?|heavily)\b", re.I)
_MEASURE = re.compile(r"\d*\.\d+|\d+(\.\d+)?\s*%")
# Age evidence is an over/under-indexing score (-1..1), not a share of the audience.
_SHARE = re.compile(r"%|\bpercent|\bshare\b|\bportion\b|\bmajority\b|\bmost of\b|\bhalf\b", re.I)


def _mentions(text: str, name: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text, re.I) is not None


def validate_claims(card: dict, claims: list[dict], foreign_names: set[str]) -> list[dict]:
    """Return only claims that cite >=1 evidence id on this card and name nothing from other cards.

    foreign_names: partner and tag names seen in this run that are NOT on this card.
    """
    ev = card["evidence"]
    own = {card["partner"]["name"].lower()} | {str(v["value"]).lower() for v in ev.values()}
    kept = []
    for c in claims:
        ids = c.get("evidence_ids") or []
        text = (c.get("text") or "").strip()
        if not text or not ids or any(i not in ev for i in ids):
            continue
        if any(n.lower() not in own and _mentions(text, n) for n in foreign_names):
            continue
        if _STRENGTH.search(text) and not _MEASURE.search(text):
            continue
        if all(i.startswith("demo:") for i in ids) and _SHARE.search(text):
            continue
        kept.append({"text": text, "evidence_ids": ids})
    return kept


def foreign_names_for(card: dict, cards: list[dict]) -> set[str]:
    names = set()
    for other in cards:
        if other is card:
            continue
        names.add(other["partner"]["name"])
        names |= {v["value"] for k, v in other["evidence"].items() if k.startswith("taste:")}
    return names


def clean_framing(text: str, fallback: str, foreign_names: set[str], allow_counts: bool = False) -> str:
    """Pitch subject/opening/ask carry no facts: no measured values (or no digits at all), no other partners' names."""
    t = (text or "").strip()[:300]
    if not t or any(_mentions(t, n) for n in foreign_names):
        return fallback
    if _MEASURE.search(t) if allow_counts else re.search(r"\d", t):
        return fallback
    return t
