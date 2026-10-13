"""Reverse mode: a creator (artist, podcast, show or person) finds the brands whose customers already love them."""
from fanfit.fixture import FixtureQlooClient
from fanfit.pipeline import Brief, find_partners, resolve, shortlist
from fanfit.presets import CREATOR_FIXTURE_PRESETS


def creator_brief(**kw):
    return Brief(**{"brand": "Juniper Ash", "subject_type": "artist", "partner_types": ["brand"], **kw})


def test_resolve_searches_the_creators_own_type():
    q = FixtureQlooClient()
    res = resolve(creator_brief(), q)
    assert res.brand and res.brand["name"] == "Juniper Ash" and res.brand["type"] == "urn:entity:artist"
    assert q.calls[0][1]["types"] == ["urn:entity:artist"]


def test_creator_brief_ranks_brands():
    q = FixtureQlooClient()
    b = creator_brief()
    cards = shortlist(resolve(b, q), b, q)
    assert cards and all(c["partner"]["type"] == "urn:entity:brand" for c in cards)


def test_subject_type_and_partner_types_are_clamped():
    assert Brief(subject_type="hacker").clean().subject_type == "brand"
    assert Brief(partner_types=["brand"]).clean().partner_types == ["brand"]
    assert creator_brief(partner_types=["brand", "artist"]).clean().partner_types == ["brand"]  # creators only look for brands


class StubQloo:
    """Answers one brand-insights call the way live Qloo does (shape seen on 2026-10-13)."""
    mode = "live"

    def get(self, path, params):
        return {"results": {"entities": [
            {"entity_id": "b1", "name": "Whoop", "types": ["urn:entity:brand"], "query": {"affinity": 0.93},
             "tags": [{"id": "t1", "name": "1920 establishments in Washington (state)"}],
             "properties": {"business_model": ["B2C", "Subscription"],
                            "audience_identity": "People who track their health and train with data",
                            "aspirational_lifestyle": ["Peak Performance", "Data-Driven Living", "Peak Performance"]}},
            {"entity_id": "b2", "name": "The Trevor Project", "types": ["urn:entity:brand"], "query": {"affinity": 0.95},
             "properties": {"business_model": ["Nonprofit"]}},
        ]}}


def test_brand_partners_drop_nonprofits_and_carry_lifestyle_and_identity():
    found = find_partners(StubQloo(), resolve(Brief(), FixtureQlooClient()), creator_brief(), "brand")
    assert [f["name"] for f in found] == ["Whoop"]
    assert found[0]["tags"] == []  # brand tags are mostly Wikipedia categories; lifestyle themes replace them
    assert found[0]["lifestyle"] == ["Peak Performance", "Data-Driven Living"]
    assert found[0]["identity"] == "People who track their health and train with data"


def test_brand_card_evidence_is_citable():
    from fanfit.pipeline import build_card
    c = {"entity_id": "b1", "name": "Whoop", "type": "urn:entity:brand", "affinity": 0.93, "tags": [],
         "lifestyle": ["Peak Performance"], "identity": "People who track their health"}
    ev = build_card(1, c, creator_brief(), {})["evidence"]
    assert ev["life:1"]["value"] == "Peak Performance"
    assert ev["identity"]["value"] == "People who track their health"


def test_creator_fixture_presets_resolve_and_rank_brands():
    for key, p in CREATOR_FIXTURE_PRESETS.items():
        q = FixtureQlooClient()
        res = resolve(p["brief"], q)
        assert res.brand and res.brand["name"] == p["brief"].brand, key
        assert shortlist(res, p["brief"], q), key


class RecordingLLM:
    """Records the system prompt and returns one claim citing affinity."""

    def __init__(self, content):
        self.content, self.systems, self.users = content, [], []

    def chat(self, messages, tools=None, json_mode=False):
        self.systems.append(messages[0]["content"])
        self.users.append(messages[1]["content"])
        return {"content": self.content}


def _brand_card():
    from fanfit.pipeline import build_card
    c = {"entity_id": "b1", "name": "Whoop", "type": "urn:entity:brand", "affinity": 0.93, "tags": [],
         "lifestyle": ["Peak Performance"], "identity": "People who track their health"}
    return build_card(1, c, creator_brief(), {})


def test_claims_for_a_brand_card_are_written_for_the_creator():
    import json
    from fanfit.agent import write_claims
    llm = RecordingLLM(json.dumps({"claims": [{"text": "Whoop's customers match Juniper Ash's fans (affinity 0.93).", "evidence_ids": ["affinity"]}]}))
    claims = write_claims(_brand_card(), [_brand_card()], "Juniper Ash", llm)
    assert claims and "creator" in llm.systems[0] and "life:" in llm.systems[0]
    assert json.loads(llm.users[0])["creator"] == "Juniper Ash"


def test_pitch_to_a_brand_is_from_the_creator():
    import json
    from fanfit.agent import draft_pitch
    llm = RecordingLLM(json.dumps({"subject": "Juniper Ash x Whoop", "opening": "Hi Whoop team,",
                                   "points": [{"text": "Your customers match my fans (affinity 0.93).", "evidence_ids": ["affinity"]}],
                                   "ask": "Open to a call?"}))
    pitch = draft_pitch(_brand_card(), [_brand_card()], "Juniper Ash", llm)
    assert pitch and "from a creator" in llm.systems[0]


def test_ai_alone_baseline_for_a_creator_asks_for_brands():
    import json
    from fanfit.agent import llm_only_partners
    llm = RecordingLLM(json.dumps({"partners": [{"name": "Patagonia", "type": "brand", "reason": "outdoorsy fans"},
                                                {"name": "Some Band", "type": "artist", "reason": "wrong type"}]}))
    picks = llm_only_partners("Juniper Ash", creator_brief(), llm)
    assert [p["name"] for p in picks] == ["Patagonia"]
    assert "brands" in llm.systems[0] and json.loads(llm.users[0])["creator_type"] == "artist"
