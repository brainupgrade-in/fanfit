"""Keep the LLM's "why this fit" claims tied to evidence on the card (SPEC §5.3)."""
from __future__ import annotations


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
        low = text.lower()
        if any(n.lower() in low and n.lower() not in own for n in foreign_names):
            continue
        kept.append({"text": text, "evidence_ids": ids})
    return kept


def foreign_names_for(card: dict, cards: list[dict]) -> set[str]:
    names = set()
    for other in cards:
        if other is card:
            continue
        names.add(other["partner"]["name"])
        names |= {v["value"] for k, v in other["evidence"].items() if k.startswith("tag:")}
    return names
