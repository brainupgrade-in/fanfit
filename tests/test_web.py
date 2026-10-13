import json

from fastapi.testclient import TestClient

from fanfit.fixture import FixtureQlooClient
from fanfit.qloo import QlooUnavailable
from fanfit.web import RateLimiter, create_app


def events(resp):
    return [json.loads(line) for line in resp.text.splitlines() if line.strip()]


def client(qloo=None, llm=False, limiter=None):
    # llm=False means "no LLM configured" (create_app treats None as "read env")
    return TestClient(create_app(qloo=qloo or FixtureQlooClient(), llm=llm, limiter=limiter))


class ClaimsLLM:
    def chat(self, messages, tools=None, json_mode=False):
        return {"content": json.dumps({"claims": [{"text": "Qloo affinity backs this partner.", "evidence_ids": ["affinity"]}]})}


class DownLLM:
    def chat(self, *a, **k):
        raise RuntimeError("down")


def resolve_preset(c, key="cold-brew"):
    evs = events(c.post("/api/resolve", json={"preset": key}))
    assert evs[-1]["type"] == "result", evs
    return evs[-1]


def shortlist_body(r):
    return {"brief": r["brief"], "brand": r["resolution"]["brand"], "tags": r["resolution"]["tags"]}


def test_page_and_config():
    c = client()
    assert c.get("/").status_code == 200 and "FanFit" in c.get("/").text
    cfg = c.get("/api/config").json()
    assert cfg["qloo_mode"] == "fixture" and cfg["llm"] is False and len(cfg["presets"]) == 3


def test_preset_flow_streams_steps_then_cards_with_claims():
    c = client(llm=ClaimsLLM())
    r = resolve_preset(c)
    assert r["status"] == "ok"
    evs = events(c.post("/api/shortlist", json=shortlist_body(r)))
    steps = [e["text"] for e in evs if e["type"] == "step"]
    assert any("Qloo insights" in s for s in steps)
    res = evs[-1]
    assert res["status"] == "ok" and res["llm"] == "ok" and len(res["cards"]) == 8
    assert all(card["claims"] for card in res["cards"])


def test_llm_off_and_llm_failure_still_return_evidence_cards():
    for llm, state in [(False, "off"), (DownLLM(), "failed")]:
        c = client(llm=llm)
        res = events(c.post("/api/shortlist", json=shortlist_body(resolve_preset(c))))[-1]
        assert res["llm"] == state and res["cards"] and all(card["claims"] == [] for card in res["cards"])


def test_free_text_without_llm_is_a_clear_error():
    ev = events(client().post("/api/resolve", json={"text": "cold brew for gen z"}))[-1]
    assert ev["type"] == "error" and ev["code"] == "llm_unavailable"


def test_unresolved_brief():
    ev = events(client().post("/api/resolve", json={"brief": {"brand": "Nope Inc", "category_terms": ["zzz"], "partner_types": ["artist"]}}))[-1]
    assert ev["status"] == "unresolved" and set(ev["resolution"]["unresolved"]) == {"Nope Inc", "zzz"}


def test_empty_shortlist():
    class Empty(FixtureQlooClient):
        def get(self, path, params):
            if params.get("filter.type", "").startswith("urn:entity:"):
                return {"results": {"entities": []}}
            return super().get(path, params)

    c = client(qloo=Empty())
    res = events(c.post("/api/shortlist", json=shortlist_body(resolve_preset(c))))[-1]
    assert res["status"] == "empty"


def test_qloo_unavailable_is_reported():
    class Down(FixtureQlooClient):
        def get(self, path, params):
            if path == "/v2/insights":
                raise QlooUnavailable("429")
            return super().get(path, params)

    c = client(qloo=Down())
    ev = events(c.post("/api/shortlist", json=shortlist_body(resolve_preset(c))))[-1]
    assert ev["type"] == "error" and ev["code"] == "qloo_unavailable"


def test_shortlist_rejects_bad_ids_before_qloo():
    c = client()
    body = shortlist_body(resolve_preset(c))
    body["tags"] = [{"id": "has spaces; drop table", "name": "x"}]
    ev = events(c.post("/api/shortlist", json=body))[-1]
    assert ev["type"] == "error"  # allowlist refuses it, nothing sent


def test_rate_limit_per_ip():
    c = client(limiter=RateLimiter(per_ip_hour=1, global_day=100))
    body = shortlist_body(resolve_preset(c))
    assert c.post("/api/shortlist", json=body).status_code == 200
    r = c.post("/api/shortlist", json=body)
    assert r.status_code == 429 and r.json()["code"] == "rate_limited"


def test_global_daily_cap():
    lim = RateLimiter(per_ip_hour=100, global_day=2)
    assert lim.allow("a") is None and lim.allow("b") is None
    assert "daily limit" in lim.allow("c")


class BaselineLLM(ClaimsLLM):
    """Answers the baseline prompt with one fixture partner and one unknown name."""

    def chat(self, messages, tools=None, json_mode=False):
        if "sponsorship strategist" in messages[0]["content"]:
            return {"content": json.dumps({"partners": [
                {"name": "Juniper Ash", "type": "artist", "reason": "indie coffeehouse sound"},
                {"name": "Taylor Swift", "type": "artist", "reason": "huge reach"},
            ]})}
        return super().chat(messages, tools, json_mode)


def test_compare_endpoint():
    c = client(llm=BaselineLLM())
    res = events(c.post("/api/compare", json=shortlist_body(resolve_preset(c))))[-1]
    assert res["type"] == "result"
    st = {s["name"]: s["qloo"]["status"] for s in res["llm_only"]}
    assert st["Taylor Swift"] == "not_found" and st["Juniper Ash"] in {"shortlisted", "low"}
    assert res["qloo_only"]


def test_compare_needs_llm():
    c = client()
    r = c.post("/api/compare", json=shortlist_body(resolve_preset(c)))
    assert r.status_code == 503 and r.json()["code"] == "llm_unavailable"


def test_rate_limit_keys_on_cloudflare_visitor_ip():
    c = client(limiter=RateLimiter(per_ip_hour=1, global_day=100))
    body = shortlist_body(resolve_preset(c))
    assert c.post("/api/shortlist", json=body, headers={"CF-Connecting-IP": "203.0.113.7"}).status_code == 200
    assert c.post("/api/shortlist", json=body, headers={"CF-Connecting-IP": "203.0.113.8"}).status_code == 200
    assert c.post("/api/shortlist", json=body, headers={"CF-Connecting-IP": "203.0.113.7"}).status_code == 429


def _fixture_as(mode, cache_dir, monkeypatch):
    """The fixture world under another mode's name; its presets stay the fictional ones."""
    from fanfit import presets
    monkeypatch.setattr("fanfit.web.presets_for", lambda _mode: presets.FIXTURE_PRESETS)
    q = FixtureQlooClient()
    q.mode, q.cache_dir = mode, cache_dir
    return q


class NoBaselineLLM(BaselineLLM):
    """Fails if asked for AI-alone picks: proves saved picks were reused."""

    def chat(self, messages, tools=None, json_mode=False):
        assert "sponsorship strategist" not in messages[0]["content"]
        return super().chat(messages, tools, json_mode)


def test_replay_reuses_the_ai_alone_picks_saved_while_live(tmp_path, monkeypatch):
    live = client(qloo=_fixture_as("live", tmp_path, monkeypatch), llm=BaselineLLM())
    body = shortlist_body(resolve_preset(live))
    first = events(live.post("/api/compare", json=body))[-1]
    assert first["type"] == "result"

    replay = client(qloo=_fixture_as("replay", tmp_path, monkeypatch), llm=NoBaselineLLM())
    again = events(replay.post("/api/compare", json=body))[-1]
    assert again["llm_only"] == first["llm_only"]


def test_live_compare_keeps_the_first_saved_picks(tmp_path, monkeypatch):
    """Once a brief's AI-alone picks are saved, later live clicks show the same picks instead of overwriting them."""
    live = client(qloo=_fixture_as("live", tmp_path, monkeypatch), llm=BaselineLLM())
    body = shortlist_body(resolve_preset(live))
    first = events(live.post("/api/compare", json=body))[-1]

    again_live = client(qloo=_fixture_as("live", tmp_path, monkeypatch), llm=NoBaselineLLM())
    again = events(again_live.post("/api/compare", json=body))[-1]
    assert again["type"] == "result" and again["llm_only"] == first["llm_only"]


def test_replay_compare_without_saved_picks_is_a_clear_error(tmp_path, monkeypatch):
    c = client(qloo=_fixture_as("replay", tmp_path, monkeypatch), llm=BaselineLLM())
    res = events(c.post("/api/compare", json=shortlist_body(resolve_preset(c))))[-1]
    assert res["type"] == "error" and res["code"] == "replay_examples_only"


def test_replay_accepts_examples_only(tmp_path, monkeypatch):
    c = client(qloo=_fixture_as("replay", tmp_path, monkeypatch), llm=ClaimsLLM())
    assert resolve_preset(c)["status"] == "ok"
    for body in ({"text": "Nike wants podcasts"}, {"brief": {"brand": "Nike"}}):
        res = events(c.post("/api/resolve", json=body))[-1]
        assert res["type"] == "error" and res["code"] == "replay_examples_only"


def test_config_lists_creator_examples_and_they_run_end_to_end():
    c = client(llm=BaselineLLM())
    cfg = c.get("/api/config").json()
    assert cfg["creator_presets"] and {p["key"] for p in cfg["creator_presets"]}.isdisjoint({p["key"] for p in cfg["presets"]})
    r = events(c.post("/api/resolve", json={"preset": cfg["creator_presets"][0]["key"]}))[-1]
    assert r["status"] == "ok" and r["brief"]["subject_type"] == "artist"
    body = {"brief": r["brief"], "brand": r["resolution"]["brand"], "tags": r["resolution"]["tags"]}
    s = events(c.post("/api/shortlist", json=body))[-1]
    assert s["cards"] and all(card["partner"]["type"] == "urn:entity:brand" for card in s["cards"])


def test_brand_side_baseline_files_keep_their_old_names(tmp_path, monkeypatch):
    """subject_type must not change the key of the saved AI-alone picks for brand briefs (judges see those)."""
    import hashlib
    from dataclasses import asdict
    from fanfit.pipeline import Brief
    live = client(qloo=_fixture_as("live", tmp_path, monkeypatch), llm=BaselineLLM())
    body = shortlist_body(resolve_preset(live))
    events(live.post("/api/compare", json=body))
    b = Brief(**body["brief"]).clean()
    old = {k: v for k, v in asdict(b).items() if k != "subject_type"}
    key = hashlib.sha256(json.dumps([body["brand"]["name"], old], sort_keys=True).encode()).hexdigest()[:32]
    assert (tmp_path / f"baseline-{key}.json").exists()
