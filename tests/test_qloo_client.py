import json

import httpx
import pytest

from fanfit.qloo import LiveQlooClient, QlooParamError, QlooUnavailable, ReplayQlooClient, check_params


def test_allows_resolved_ids_and_enums():
    check_params("/v2/insights", {
        "filter.type": "urn:entity:podcast",
        "signal.interests.entities": ["636E1B95-6232-43E1-BDFE-37CD209C2CE3"],
        "signal.interests.tags": ["urn:tag:genre:media:horror"],
        "signal.demographics.age": "25_to_29",
        "feature.explainability": True,
        "take": 20,
    })


@pytest.mark.parametrize("path,params", [
    ("/v2/insights", {"signal.interests.entities": ["has spaces in it"]}),
    ("/search", {"query": "x" * 41}),  # long free text = a pasted brief
    ("/search", {"email": "a@b.com"}),  # unknown param
    ("/v2/insights", {"signal.demographics.age": "29"}),  # not in the enum
    ("/recs", {}),  # legacy endpoint
])
def test_rejects_free_text_and_unknown_params(path, params):
    with pytest.raises(QlooParamError):
        check_params(path, params)


def _live(tmp_path, handler):
    http = httpx.Client(base_url="https://test", transport=httpx.MockTransport(handler))
    return LiveQlooClient("k", tmp_path, http=http)


def test_live_caches_then_replay_serves_from_cache(tmp_path):
    hits = []

    def handler(req):
        hits.append(str(req.url))
        return httpx.Response(200, json={"results": [{"entity_id": "A", "name": "A"}]})

    live = _live(tmp_path, handler)
    p = {"query": "coffee", "take": 3}
    assert live.get("/search", p) == live.get("/search", p)
    assert len(hits) == 1
    assert ReplayQlooClient(tmp_path).get("/search", p)["results"][0]["name"] == "A"


def test_live_retries_once_on_429_then_gives_up(tmp_path):
    hits = []

    def handler(req):
        hits.append(1)
        return httpx.Response(429, json={})

    with pytest.raises(QlooUnavailable):
        _live(tmp_path, handler).get("/search", {"query": "coffee"})
    assert len(hits) == 2


def test_replay_miss_is_unavailable(tmp_path):
    with pytest.raises(QlooUnavailable):
        ReplayQlooClient(tmp_path).get("/search", {"query": "nope"})


def test_429_backs_off_then_succeeds(tmp_path, monkeypatch):
    import fanfit.qloo as qm

    slept, calls = [], []
    monkeypatch.setattr(qm.time, "sleep", lambda s: slept.append(s))

    def handler(req):
        calls.append(1)
        return httpx.Response(429, json={}) if len(calls) == 1 else httpx.Response(200, json={"results": []})

    assert _live(tmp_path, handler).get("/search", {"query": "coffee"}) == {"results": []}
    assert len(calls) == 2 and slept and slept[0] >= 1.0


def test_400_raises_bad_request_with_qloo_message(tmp_path):
    from fanfit.qloo import QlooBadRequest

    def handler(req):
        return httpx.Response(400, json={"errors": [{"message": "invalid location"}]})

    with pytest.raises(QlooBadRequest, match="invalid location"):
        _live(tmp_path, handler).get("/v2/insights", {"filter.type": "urn:entity:artist", "signal.location.query": "Londn"})


def test_throttle_spaces_requests():
    from fanfit.qloo import Throttle

    t = Throttle(per_second=4)
    now = [100.0]
    waits = []
    t._clock = lambda: now[0]
    t._sleep = lambda s: (waits.append(s), now.__setitem__(0, now[0] + s))
    for _ in range(5):
        t.wait()
    assert abs(sum(waits) - 1.0) < 1e-6  # 5 requests at 4/s need 1s of spacing in total
