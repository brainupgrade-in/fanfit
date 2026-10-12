from fanfit.fixture import FixtureQlooClient
from fanfit.pipeline import MAX_CARDS, Brief, resolve, shortlist
from fanfit.presets import PRESETS
from fanfit.qloo import QlooUnavailable, check_params


def test_every_preset_resolves_and_yields_ranked_cards():
    for key, p in PRESETS.items():
        q = FixtureQlooClient()
        res = resolve(p["brief"], q)
        assert res.brand and res.brand["name"] == p["brief"].brand, key
        cards = shortlist(res, p["brief"], q)
        assert 0 < len(cards) <= MAX_CARDS
        affs = [c["affinity"] for c in cards]
        assert affs == sorted(affs, reverse=True)
        assert all("affinity" in c["evidence"] for c in cards)
        assert any(k.startswith("tag:") for c in cards for k in c["evidence"]), key


def test_brand_signal_changes_ranking_vs_no_signal():
    """Fixture analogue of SPEC §9.3: the brand signal must reorder candidates."""
    q = FixtureQlooClient()
    b = PRESETS["cold-brew"]["brief"]
    with_signal = [c["partner"]["name"] for c in shortlist(resolve(b, q), b, q)]
    bare = Brief(partner_types=b.partner_types)
    without = [c["partner"]["name"] for c in shortlist(resolve(bare, q), bare, q)]
    assert with_signal != without


def test_every_request_sent_passes_the_allowlist():
    q = FixtureQlooClient()
    b = PRESETS["trail"]["brief"]
    shortlist(resolve(b, q), b, q)
    for path, params in q.calls:
        check_params(path, params)  # raises on violation
    assert all(len(str(v)) <= 40 for _, p in q.calls for k, v in p.items() if k in ("query", "filter.query"))


def test_unknown_brand_is_reported_unresolved():
    res = resolve(Brief(brand="No Such Brand", category_terms=["cold brew"]), FixtureQlooClient())
    assert res.brand is None and "No Such Brand" in res.unresolved and res.tags


def test_brief_clean_clamps_long_text_and_bad_enums():
    b = Brief(brand="x" * 200, age="twenties", partner_types=["blog"]).clean()
    assert len(b.brand) == 40 and b.age is None and b.partner_types == ["artist"]


def test_enrichment_failure_still_ships_cards():
    class Flaky(FixtureQlooClient):
        def get(self, path, params):
            if params.get("filter.type") in ("urn:heatmap", "urn:demographics"):
                raise QlooUnavailable("429")
            return super().get(path, params)

    q, b, trace = Flaky(), PRESETS["tour"]["brief"], []
    cards = shortlist(resolve(b, q), b, q, trace)
    assert cards and not any(k.startswith("geo:") for c in cards for k in c["evidence"])
    assert any("enrichment skipped" in t for t in trace)
