"""Fill the deployed Qloo cache for every example, then prove replay mode can serve them with no key.

Runs inside the fanfit pod (the image has no scripts/, so pipe it in):
  kubectl -n fanfit exec -i deploy/fanfit -- sh -c 'cat > /tmp/warm.py && cd /app && PYTHONPATH=/app python /tmp/warm.py live' < scripts/warm_cache.py
  kubectl -n fanfit exec deploy/fanfit -- sh -c 'cd /app && QLOO_API_KEY= PYTHONPATH=/app python /tmp/warm.py replay'
live: each example through resolve -> shortlist -> compare, the same web code path a visitor's clicks take.
replay: the same clicks from the cache alone; exits non-zero if any example fails.
"""
import json, os, sys
from pathlib import Path
from fastapi.testclient import TestClient
from fanfit.web import RateLimiter, create_app
from fanfit.qloo import ReplayQlooClient, make_client

def ev(r): return [json.loads(l) for l in r.text.splitlines() if l.strip()]

def run(app, label):
    c = TestClient(app)
    cfg = c.get("/api/config").json()
    keys = [p["key"] for p in cfg["presets"] + cfg.get("creator_presets", [])]
    bad = 0
    for k in keys:
        r = ev(c.post("/api/resolve", json={"preset": k}))[-1]
        if r["type"] != "result": print(label, k, "resolve", r); bad += 1; continue
        body = {"brief": r["brief"], "brand": r["resolution"]["brand"], "tags": r["resolution"]["tags"]}
        s = ev(c.post("/api/shortlist", json=body))[-1]
        cmp = ev(c.post("/api/compare", json=body))[-1]
        ok = s.get("status") == "ok" and cmp["type"] == "result"
        bad += not ok
        print(f"{label:6} {k:15} cards={len(s.get('cards', []))} llm={s.get('llm')} compare={cmp['type']}"
              f" ai_picks={len(cmp.get('llm_only', []))} in_top8={sum(x['qloo']['status']=='shortlisted' for x in cmp.get('llm_only', []))}"
              + ("" if ok else f" !! {s.get('message') or cmp.get('message')}"))
    return bad

big = RateLimiter(10**6, 10**6)
mode = sys.argv[1]
if mode == "live":
    sys.exit(run(create_app(qloo=make_client("live"), limiter=big), "live"))
sys.exit(run(create_app(qloo=ReplayQlooClient(Path(os.environ["QLOO_CACHE_DIR"])), limiter=big), "replay"))
