import json

from fastapi.testclient import TestClient

from fanfit.agent import draft_pitch
from fanfit.fixture import FixtureQlooClient
from fanfit.pipeline import resolve, shortlist
from fanfit.presets import PRESETS
from fanfit.web import create_app


def cards():
    q = FixtureQlooClient()
    b = PRESETS["cold-brew"]["brief"]
    return shortlist(resolve(b, q), b, q)


class PitchLLM:
    def __init__(self, reply):
        self.reply = reply

    def chat(self, messages, tools=None, json_mode=False):
        return {"content": self.reply if isinstance(self.reply, str) else json.dumps(self.reply)}


def test_pitch_keeps_only_grounded_points_and_clean_framing():
    cs = cards()
    card, other = cs[0], cs[1]["partner"]["name"]
    tag = next(k for k in card["evidence"] if k.startswith("tag:"))
    llm = PitchLLM({
        "subject": f"Partnership idea: Northbound Cold Brew x {card['partner']['name']}",
        "opening": f"Hi {card['partner']['name']} team, we love what you do.",
        "points": [
            {"text": f"Your audience shares our fans' taste for {card['evidence'][tag]['value']}.", "evidence_ids": [tag]},
            {"text": "Invented stat: 90% overlap.", "evidence_ids": []},
            {"text": f"Like {other}, you'd be great.", "evidence_ids": ["affinity"]},
        ],
        "ask": "Could we set up a 20-minute call next week?",
    })
    p = draft_pitch(card, cs, "Northbound Cold Brew", llm)
    assert len(p["points"]) == 1 and p["points"][0]["evidence_ids"] == [tag]
    assert p["subject"].startswith("Partnership idea")
    assert p["ask"].startswith("Could we")  # a duration is a request, not a claimed fact
    assert card["partner"]["name"] in p["opening"]


def test_pitch_framing_with_numbers_or_foreign_names_falls_back():
    cs = cards()
    card, other = cs[0], cs[1]["partner"]["name"]
    llm = PitchLLM({"subject": f"You and {other}", "opening": "Your fans are 87% coffee lovers.",
                    "points": [{"text": "Qloo affinity backs this.", "evidence_ids": ["affinity"]}], "ask": "Talk soon?"})
    p = draft_pitch(card, cs, "Northbound Cold Brew", llm)
    assert other not in p["subject"] and "87%" not in p["opening"]


def test_pitch_bad_json_or_no_points_is_none():
    cs = cards()
    assert draft_pitch(cs[0], cs, "B", PitchLLM("nope")) is None
    assert draft_pitch(cs[0], cs, "B", PitchLLM({"subject": "s", "opening": "o", "points": [], "ask": "a"})) is None


def test_pitch_endpoint():
    cs = cards()
    llm = PitchLLM({"subject": "Partnership idea", "opening": "Hello team.",
                    "points": [{"text": "Qloo affinity backs this.", "evidence_ids": ["affinity"]}], "ask": "Shall we talk?"})
    c = TestClient(create_app(qloo=FixtureQlooClient(), llm=llm))
    body = {"brand_label": "Northbound Cold Brew", "card": cs[0], "others": [x["partner"]["name"] for x in cs[1:]]}
    r = c.post("/api/pitch", json=body)
    assert r.status_code == 200 and r.json()["pitch"]["points"]
    c2 = TestClient(create_app(qloo=FixtureQlooClient(), llm=False))
    assert c2.post("/api/pitch", json=body).status_code == 503


def test_pitch_only_sees_supportive_evidence():
    from fanfit.agent import supportive_evidence

    ev = {
        "affinity": {"value": 0.3},
        "tag:a": {"value": "trail running"},
        "demo:30_to_34": {"value": 0.005},
        "geo:Portland": {"value": "Portland", "affinity": 0.88},
        "geo:Miami": {"value": "Miami", "affinity": 0.12},
        "trend": {"value": -8},
    }
    assert set(supportive_evidence({"evidence": ev})) == {"affinity", "tag:a", "geo:Portland"}
    ev["demo:30_to_34"]["value"] = 0.29
    ev["trend"]["value"] = 12
    assert {"demo:30_to_34", "trend"} <= set(supportive_evidence({"evidence": ev}))
