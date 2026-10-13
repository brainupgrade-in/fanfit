"""FastAPI app: one page plus two streaming endpoints (resolve, shortlist).

Each endpoint streams newline-delimited JSON events so the UI can show the agent's steps live:
  {"type": "step", "text": ...}  ...  then one {"type": "result", ...} or {"type": "error", "code": ..., "message": ...}
Run: uv run uvicorn fanfit.web:app --reload
"""
from __future__ import annotations

import json
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

from fanfit.agent import OpenAICompatLLM, add_claims, resolve_with_agent
from fanfit.pipeline import Brief, Resolution, resolve, shortlist
from fanfit.presets import PRESETS
from fanfit.qloo import QlooUnavailable, make_client

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
STATIC = Path(__file__).resolve().parent / "static"


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

    return StreamingResponse(gen(), media_type="application/x-ndjson")


def create_app(qloo=None, llm=None, limiter: RateLimiter | None = None) -> FastAPI:
    qloo = qloo or make_client()
    llm = llm if llm is not None else OpenAICompatLLM.from_env()
    limiter = limiter or RateLimiter(int(os.environ.get("RATE_PER_IP_HOUR", 20)), int(os.environ.get("RATE_GLOBAL_DAY", 500)))
    app = FastAPI(title="FanFit")
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    def ip(req: Request) -> str:
        return req.headers.get("cf-connecting-ip") or (req.client.host if req.client else "?")

    def limited(req: Request):
        msg = limiter.allow(ip(req))
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

    @app.post("/api/shortlist")
    def api_shortlist(body: ShortlistIn, req: Request):
        if resp := limited(req):
            return resp

        def work(s: _Stream):
            brief = Brief(**body.brief.model_dump()).clean()
            res = Resolution(
                brand=body.brand.model_dump() if body.brand else None,
                brand_candidates=[],
                tags=[t.model_dump() for t in body.tags],
                unresolved=[],
            )
            if not res.brand and not res.tags:
                return {"type": "error", "code": "bad_request", "message": "Confirm a brand or at least one category first."}
            s.append("Ranking partners by Qloo taste affinity…")
            cards = shortlist(res, brief, qloo, s)
            if not cards:
                return {"type": "result", "status": "empty", "cards": [], "llm": "skipped"}
            llm_state = "off"
            if llm:
                s.append(f"Writing evidence-backed rationale for {len(cards)} partners…")
                label = res.brand["name"] if res.brand else ", ".join(t["name"] for t in res.tags)
                llm_state = "ok" if add_claims(cards, label, llm) else "failed"
            return {"type": "result", "status": "ok", "cards": cards, "llm": llm_state}

        return _stream(work)

    return app


app = create_app()
