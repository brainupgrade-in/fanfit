"""FastAPI app: one page plus two streaming endpoints (resolve, shortlist).

Each endpoint streams newline-delimited JSON events so the UI can show the agent's steps live:
  {"type": "step", "text": ...}  ...  then one {"type": "result", ...} or {"type": "error", "code": ..., "message": ...}
Run: uv run uvicorn fanfit.web:app --reload
"""
from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
from collections import defaultdict, deque
from dataclasses import asdict
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from fanfit.agent import OpenAICompatLLM, add_claims, llm_only_partners, resolve_with_agent
from fanfit.pipeline import MAX_CARDS, Brief, Resolution, compare_with_qloo, rank_pool, resolve, shortlist
from fanfit.presets import PRESETS
from fanfit.qloo import QlooUnavailable, make_client

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
STATIC = Path(__file__).resolve().parent / "static"
log = logging.getLogger("uvicorn.error")


def client_ip(req: Request) -> str:
    """Behind Cloudflare -> ingress-nginx the socket address is the controller pod; Cloudflare's header is the visitor."""
    return req.headers.get("cf-connecting-ip") or (req.client.host if req.client else "?")


def masked(ip: str) -> str:
    parts = ip.split(".")
    return ".".join(parts[:2] + ["x", "x"]) if len(parts) == 4 else ip.split(":")[0] + ":…"


class RateLimiter:
    """Per-IP hourly limit plus a global daily cap on runs (SPEC §6). In memory: one replica only."""

    def __init__(self, per_ip_hour: int, global_day: int):
        self.per_ip_hour, self.global_day = per_ip_hour, global_day
        self.ip_hits: dict[str, deque] = defaultdict(deque)
        self.day_hits: deque = deque()
        self.lock = threading.Lock()

    def allow(self, ip: str, now: float | None = None) -> str | None:
        now = now or time.time()
        with self.lock:
            hits = self.ip_hits[ip]
            while hits and hits[0] < now - 3600:
                hits.popleft()
            while self.day_hits and self.day_hits[0] < now - 86400:
                self.day_hits.popleft()
            if len(self.day_hits) >= self.global_day:
                return "The demo's daily limit is reached. Try a preset; they're served from cache."
            if len(hits) >= self.per_ip_hour:
                return "You've run a lot of briefs this hour. Please try again a bit later."
            hits.append(now)
            self.day_hits.append(now)
            return None


class BriefIn(BaseModel):
    brand: str | None = Field(None, max_length=200)
    category_terms: list[str] = Field(default_factory=list, max_length=3)
    age: str | None = None
    gender: str | None = None
    market: str | None = Field(None, max_length=200)
    partner_types: list[str] = Field(default_factory=lambda: ["artist", "podcast"], max_length=4)


class ResolveIn(BaseModel):
    preset: str | None = None
    text: str | None = Field(None, max_length=1000)
    brief: BriefIn | None = None


class EntityIn(BaseModel):
    entity_id: str = Field(max_length=120)
    name: str = Field(max_length=200)
    type: str = Field(max_length=60)


class TagIn(BaseModel):
    id: str = Field(max_length=120)
    name: str = Field(max_length=200)


class ShortlistIn(BaseModel):
    brief: BriefIn
    brand: EntityIn | None = None
    tags: list[TagIn] = Field(default_factory=list, max_length=3)


class _Stream:
    """Collects pipeline trace lines into a queue; `append` makes it a drop-in for the trace list."""

    def __init__(self):
        self.q: queue.Queue = queue.Queue()

    def append(self, text: str) -> None:
        self.q.put({"type": "step", "text": text})


def _stream(work) -> StreamingResponse:
    """Run work(stream) in a thread and stream its events as NDJSON."""
    s = _Stream()

    def run():
        try:
            s.q.put(work(s))
        except QlooUnavailable as e:
            s.q.put({"type": "error", "code": "qloo_unavailable", "message": f"Qloo didn't respond ({e}). Try again, or pick a preset."})
        except Exception as e:  # noqa: BLE001 - last-resort guard so the stream always ends
            s.q.put({"type": "error", "code": "internal", "message": f"Something went wrong: {type(e).__name__}"})
        s.q.put(None)

    threading.Thread(target=run, daemon=True).start()

    def gen():
        while (ev := s.q.get()) is not None:
            yield json.dumps(ev) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson", headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"})


def create_app(qloo=None, llm=None, limiter: RateLimiter | None = None) -> FastAPI:
    qloo = qloo or make_client()
    llm = llm if llm is not None else OpenAICompatLLM.from_env()
    limiter = limiter or RateLimiter(int(os.environ.get("RATE_PER_IP_HOUR", 20)), int(os.environ.get("RATE_GLOBAL_DAY", 500)))
    app = FastAPI(title="FanFit")
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    def limited(req: Request):
        ip = client_ip(req)
        msg = limiter.allow(ip)
        log.info("run %s from %s%s", req.url.path, masked(ip), " (rate limited)" if msg else "")
        return JSONResponse({"type": "error", "code": "rate_limited", "message": msg}, status_code=429) if msg else None

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/api/config")
    def config():
        return {
            "qloo_mode": qloo.mode,
            "llm": bool(llm),
            "presets": [{"key": k, "title": p["title"], "text": p["text"]} for k, p in PRESETS.items()],
        }

    @app.post("/api/resolve")
    def api_resolve(body: ResolveIn, req: Request):
        if body.text and not body.preset and (resp := limited(req)):
            return resp

        def work(s: _Stream):
            if body.preset:
                if body.preset not in PRESETS:
                    return {"type": "error", "code": "bad_request", "message": "Unknown preset."}
                brief = PRESETS[body.preset]["brief"]
                res = resolve(brief, qloo)
                s.append(f"Preset resolved: {res.brand['name'] if res.brand else 'no brand'}")
            elif body.text:
                if not llm:
                    return {"type": "error", "code": "llm_unavailable", "message": "Free-text briefs need the AI model, which is offline. Use the form or a preset."}
                s.append("Reading your brief…")
                brief, res = resolve_with_agent(body.text, qloo, llm, s)
            elif body.brief:
                brief = Brief(**body.brief.model_dump())
                s.append("Looking up your brand and categories in Qloo…")
                res = resolve(brief, qloo)
            else:
                return {"type": "error", "code": "bad_request", "message": "Enter a brief or pick a preset."}
            status = "ok" if (res.brand or res.tags) else "unresolved"
            return {"type": "result", "status": status, "brief": asdict(brief.clean()), "resolution": asdict(res)}

        return _stream(work)

    def _confirmed(body: ShortlistIn) -> tuple[Brief, Resolution]:
        res = Resolution(
            brand=body.brand.model_dump() if body.brand else None,
            brand_candidates=[],
            tags=[t.model_dump() for t in body.tags],
            unresolved=[],
        )
        return Brief(**body.brief.model_dump()).clean(), res

    def _label(res: Resolution) -> str:
        return res.brand["name"] if res.brand else ", ".join(t["name"] for t in res.tags)

    @app.post("/api/shortlist")
    def api_shortlist(body: ShortlistIn, req: Request):
        if resp := limited(req):
            return resp

        def work(s: _Stream):
            brief, res = _confirmed(body)
            if not res.brand and not res.tags:
                return {"type": "error", "code": "bad_request", "message": "Confirm a brand or at least one category first."}
            s.append("Ranking partners by Qloo taste affinity…")
            cards = shortlist(res, brief, qloo, s)
            if not cards:
                return {"type": "result", "status": "empty", "cards": [], "llm": "skipped"}
            llm_state = "off"
            if llm:
                s.append(f"Writing evidence-backed rationale for {len(cards)} partners…")
                llm_state = "ok" if add_claims(cards, _label(res), llm) else "failed"
            return {"type": "result", "status": "ok", "cards": cards, "llm": llm_state}

        return _stream(work)

    @app.post("/api/compare")
    def api_compare(body: ShortlistIn, req: Request):
        """Qloo vs. AI alone (SPEC §5.4): same brief, same model, no Qloo tools; then check its picks in Qloo."""
        if not llm:
            return JSONResponse({"type": "error", "code": "llm_unavailable", "message": "The comparison needs the AI model, which is offline."}, status_code=503)
        if resp := limited(req):
            return resp

        def work(s: _Stream):
            brief, res = _confirmed(body)
            if not res.brand and not res.tags:
                return {"type": "error", "code": "bad_request", "message": "Confirm a brand or at least one category first."}
            s.append("Asking the same AI model for partners, with no Qloo data…")
            try:
                suggestions = llm_only_partners(_label(res), brief, llm)
            except Exception:  # noqa: BLE001
                return {"type": "error", "code": "llm_failed", "message": "The AI model didn't answer. Try again in a moment."}
            s.append(f"AI alone suggested {len(suggestions)} partners. Checking each one in Qloo…")
            pool = rank_pool(res, brief, qloo)
            cards = [{"rank": i, "partner": {k: c[k] for k in ("entity_id", "name", "type")}, "affinity": c["affinity"]}
                     for i, c in enumerate(pool[:MAX_CARDS], 1)]
            return {"type": "result", **compare_with_qloo(qloo, suggestions, pool, cards)}

        return _stream(work)

    return app


app = create_app()
