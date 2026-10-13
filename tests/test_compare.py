import json

from fanfit.agent import llm_only_partners
from fanfit.fixture import FixtureQlooClient
from fanfit.pipeline import compare_with_qloo, rank_pool, resolve, shortlist
from fanfit.presets import PRESETS


class Suggests:
    def __init__(self, partners):
        self.partners = partners
        self.calls = []

    def chat(self, messages, tools=None, json_mode=False):
        self.calls.append((messages, tools))
        return {"content": json.dumps({"partners": self.partners})}


def setup():
    q = FixtureQlooClient()
    b = PRESETS["cold-brew"]["brief"]
    res = resolve(b, q)
    return q, b, res


def test_llm_only_gets_no_tools_and_clean_output():
    llm = Suggests([{"name": "Juniper Ash", "type": "artist", "reason": "coffee vibes"},
                    {"name": "x" * 300, "type": "artist", "reason": "too long"},
                    {"name": "Some Blog", "type": "blog", "reason": "bad type"}])
    out = llm_only_partners("Northbound Cold Brew", PRESETS["cold-brew"]["brief"], llm)
    assert llm.calls[0][1] is None  # no tools: it's the AI-alone baseline
    assert [p["name"] for p in out] == ["Juniper Ash"]


def test_compare_marks_ranked_low_and_unknown_and_qloo_only():
    q, b, res = setup()
    pool = rank_pool(res, b, q)
    cards = shortlist(res, b, q)
    top_name = cards[0]["partner"]["name"]
    worst = pool[-1]["name"]
    suggestions = [
        {"name": top_name, "type": cards[0]["partner"]["type"].split(":")[-1], "reason": "r"},
        {"name": worst, "type": pool[-1]["type"].split(":")[-1], "reason": "r"},
        {"name": "Famous Real Band", "type": "artist", "reason": "r"},
    ]
    cmp = compare_with_qloo(q, suggestions, pool, cards)
    by = {s["name"]: s["qloo"] for s in cmp["llm_only"]}
    assert by[top_name]["status"] == "shortlisted" and by[top_name]["rank"] == 1
    assert by[worst]["status"] == "low" and by[worst]["rank"] == len(pool)
    assert by["Famous Real Band"]["status"] == "not_found"
    assert top_name not in [c["name"] for c in cmp["qloo_only"]]
    assert len(cmp["qloo_only"]) == len(cards) - 1


def test_compare_lookups_pass_allowlist():
    q, b, res = setup()
    pool = rank_pool(res, b, q)
    n = len(q.calls)
    compare_with_qloo(q, [{"name": "A" * 40, "type": "podcast", "reason": ""}], pool, [])
    assert q.calls[n][0] == "/search" and len(q.calls[n][1]["query"]) <= 40
