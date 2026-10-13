import json

from fanfit.agent import resolve_with_agent, write_claims
from fanfit.fixture import FixtureQlooClient
from fanfit.grounding import validate_claims
from fanfit.pipeline import resolve, shortlist
from fanfit.presets import PRESETS


class ScriptedLLM:
    """Returns pre-baked assistant messages in order; records what it was sent."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.sent = []

    def chat(self, messages, tools=None, json_mode=False):
        self.sent.append(messages)
        return self.replies.pop(0)


def call(name, i, **args):
    return {"role": "assistant", "content": None,
            "tool_calls": [{"id": f"c{i}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


def test_agent_resolves_brief_and_only_accepts_ids_it_saw():
    q = FixtureQlooClient()
    brand_id = q.get("/search", {"query": "Northbound", "types": ["urn:entity:brand"]})["results"][0]["entity_id"]
    tag_id = q.get("/v2/tags", {"filter.query": "cold brew"})["results"]["tags"][0]["id"]
    llm = ScriptedLLM([
        call("search_brand", 1, term="Northbound Cold Brew"),
        call("search_tags", 2, term="cold brew"),
        call("finish", 3, brand_entity_id=brand_id, tag_ids=[tag_id, "urn:tag:invented"], age="25_to_29",
             market="Austin", partner_types=["artist", "blog"]),
    ])
    trace = []
    brief, res = resolve_with_agent(PRESETS["cold-brew"]["text"], q, llm, trace)
    assert res.brand["entity_id"] == brand_id
    assert [t["id"] for t in res.tags] == [tag_id]  # invented tag dropped
    assert brief.partner_types == ["artist"]  # invalid type dropped
    assert len(trace) == 2


def test_agent_rejects_brand_id_it_never_searched():
    q = FixtureQlooClient()
    llm = ScriptedLLM([call("finish", 1, brand_entity_id="MADE-UP", tag_ids=[], partner_types=["artist"])])
    _, res = resolve_with_agent("anything", q, llm, [])
    assert res.brand is None


def _cards():
    q = FixtureQlooClient()
    b = PRESETS["cold-brew"]["brief"]
    return shortlist(resolve(b, q), b, q)


def test_validator_keeps_only_grounded_claims():
    cards = _cards()
    card = cards[0]
    tag_key = next(k for k in card["evidence"] if k.startswith("taste:"))
    other = cards[1]["partner"]["name"]
    claims = [
        {"text": "Strong Qloo affinity (0.42) with the brand.", "evidence_ids": ["affinity"]},
        {"text": f"Fans share a taste for {card['evidence'][tag_key]['value']}.", "evidence_ids": [tag_key]},
        {"text": "No evidence cited.", "evidence_ids": []},
        {"text": "Cites a key not on the card.", "evidence_ids": ["taste:urn:tag:invented"]},
        {"text": f"Also great alongside {other}.", "evidence_ids": ["affinity"]},
    ]
    from fanfit.grounding import foreign_names_for

    kept = validate_claims(card, claims, foreign_names_for(card, cards))
    assert [c["text"] for c in kept] == [claims[0]["text"], claims[1]["text"]]


def test_write_claims_survives_bad_json():
    cards = _cards()
    llm = ScriptedLLM([{"role": "assistant", "content": "not json"}])
    assert write_claims(cards[0], cards, "Northbound Cold Brew", llm) == []


def test_strength_words_need_a_number():
    cards = _cards()
    card = cards[0]
    claims = [
        {"text": "Appeals strongly to 25-29 year olds.", "evidence_ids": ["affinity"]},
        {"text": "High affinity (0.42) with the brand.", "evidence_ids": ["affinity"]},
    ]
    from fanfit.grounding import foreign_names_for

    kept = validate_claims(card, claims, foreign_names_for(card, cards))
    assert [c["text"] for c in kept] == ["High affinity (0.42) with the brand."]


def test_add_claims_runs_every_card_and_reports_llm_failure():
    from fanfit.agent import add_claims

    cards = _cards()

    class Echo:
        def chat(self, messages, tools=None, json_mode=False):
            return {"content": json.dumps({"claims": [{"text": "Qloo affinity backs this.", "evidence_ids": ["affinity"]}]})}

    assert add_claims(cards, "Northbound Cold Brew", Echo()) is True
    assert all(len(c["claims"]) == 1 for c in cards)

    class Down:
        def chat(self, *a, **k):
            raise RuntimeError("provider down")

    cards = _cards()
    assert add_claims(cards, "Northbound Cold Brew", Down()) is False
    assert all(c["claims"] == [] for c in cards)


def test_age_index_is_not_described_as_a_share():
    cards = _cards()
    card = cards[0]
    demo = next(k for k in card["evidence"] if k.startswith("demo:"))
    from fanfit.grounding import foreign_names_for

    claims = [
        {"text": "70% of its listeners are 25-29.", "evidence_ids": [demo]},
        {"text": "Most of its audience is in the target band.", "evidence_ids": [demo]},
        {"text": "It over-indexes with 25-29 year olds (+0.70).", "evidence_ids": [demo]},
    ]
    kept = validate_claims(card, claims, foreign_names_for(card, cards))
    assert [c["text"] for c in kept] == [claims[2]["text"]]


def test_profile_evidence_is_not_tied_to_the_market():
    card = {"partner": {"name": "A"}, "evidence": {"demo:30_to_34": {"value": 0.56}, "market": {"value": "Denver"},
                                                   "affinity": {"value": 0.98}, "taste:t1": {"value": "Indie"}}}
    claims = [
        {"text": "In Denver, the audience skews 30-34 (+0.56).", "evidence_ids": ["demo:30_to_34", "market"]},
        {"text": "Denver fans over-index with 30-34 year olds (+0.56).", "evidence_ids": ["demo:30_to_34"]},
        {"text": "In Denver, fans are into Indie.", "evidence_ids": ["taste:t1", "market"]},
        {"text": "It over-indexes with 30-34 year olds (+0.56).", "evidence_ids": ["demo:30_to_34"]},
        {"text": "Ranked for Denver with an affinity of 0.98.", "evidence_ids": ["affinity", "market"]},
    ]
    kept = validate_claims(card, claims, set())
    assert [c["text"] for c in kept] == [claims[3]["text"], claims[4]["text"]]


def test_raw_scores_are_rounded():
    card = {"partner": {"name": "A"}, "evidence": {"affinity": {"value": 0.9805}}}
    kept = validate_claims(card, [{"text": "An affinity of 0.9805 with the brand.", "evidence_ids": ["affinity"]}], set())
    assert kept[0]["text"] == "An affinity of 0.98 with the brand."


def test_foreign_names_match_whole_words_only():
    card = {"partner": {"name": "A"}, "evidence": {"affinity": {"value": 0.5}}}
    kept = validate_claims(card, [{"text": "A popular pick (0.50).", "evidence_ids": ["affinity"]},
                                  {"text": "Better than Pop fans think.", "evidence_ids": ["affinity"]}], {"Pop"})
    assert [c["text"] for c in kept] == ["A popular pick (0.50)."]
