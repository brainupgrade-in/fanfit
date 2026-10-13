"""Qloo access behind one interface: fixture, live (with disk cache) and replay modes.

Every request passes `check_params` first, so no client can send user free text or
unknown parameters to Qloo (SPEC §8).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Protocol

import httpx

BASE_URL = "https://hackathon.api.qloo.com"  # hackathon keys only work here
# Live limits seen on 2026-10-13: 5 requests/second and 10,000/month (x-*-ratelimit-* headers).
PER_SECOND = 4
log = logging.getLogger("uvicorn.error")

AGE_BANDS = {"24_and_younger", "25_to_29", "30_to_34", "35_to_44", "45_to_54", "55_and_older"}
GENDERS = {"male", "female"}
PATHS = {"/search", "/v2/tags", "/v2/insights"}

TEXT_MAX = 40
_ID = re.compile(r"^[A-Za-z0-9:_.\-]{1,120}$")  # Qloo entity UUIDs and urn:... tag ids
_TYPE = re.compile(r"^urn:(entity:[a-z_]+|heatmap|demographics)$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _text(v: str) -> bool:
    return isinstance(v, str) and 0 < len(v) <= TEXT_MAX


def _ids(v) -> bool:
    items = v.split(",") if isinstance(v, str) else v
    return isinstance(items, list) and 0 < len(items) <= 25 and all(_ID.match(str(i)) for i in items)


ALLOWED = {
    "query": _text,
    "filter.query": _text,
    "filter.location.query": _text,
    "signal.location.query": _text,
    "types": lambda v: all(_TYPE.match(t) for t in (v.split(",") if isinstance(v, str) else v)),
    "filter.type": lambda v: bool(_TYPE.match(v)),
    "signal.interests.entities": _ids,
    "signal.interests.tags": _ids,
    "filter.tags": _ids,
    "operator.signal.interests.tags": lambda v: v in {"union", "intersection"},
    "signal.demographics.age": lambda v: v in AGE_BANDS,
    "signal.demographics.gender": lambda v: v in GENDERS,
    "feature.explainability": lambda v: v in (True, "true"),
    "filter.start_date": lambda v: bool(_DATE.match(v)),
    "filter.end_date": lambda v: bool(_DATE.match(v)),
    "take": lambda v: isinstance(v, int) and 1 <= v <= 50,
}


class QlooParamError(ValueError):
    pass


def check_params(path: str, params: dict) -> None:
    if path not in PATHS:
        raise QlooParamError(f"path not allowed: {path}")
    for k, v in params.items():
        rule = ALLOWED.get(k)
        if rule is None or not rule(v):
            raise QlooParamError(f"param not allowed: {k}={v!r}")


def _wire(params: dict) -> dict:
    return {k: ",".join(v) if isinstance(v, list) else ("true" if v is True else v) for k, v in params.items()}


def cache_key(path: str, params: dict) -> str:
    raw = json.dumps([path, sorted(_wire(params).items())])
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


class QlooClient(Protocol):
    mode: str

    def get(self, path: str, params: dict) -> dict: ...


class QlooUnavailable(RuntimeError):
    """Raised when a response can't be produced (rate limit, timeout, replay miss)."""


class QlooBadRequest(ValueError):
    """Qloo rejected the request (400), e.g. a location it doesn't recognise. Carries Qloo's message."""


class Throttle:
    """Spaces calls so they stay under Qloo's per-second limit, across threads."""

    def __init__(self, per_second: float):
        self.gap = 1.0 / per_second
        self.next_at = 0.0
        self.lock = threading.Lock()
        self._clock, self._sleep = time.monotonic, time.sleep

    def wait(self) -> None:
        with self.lock:
            now = self._clock()
            at = max(now, self.next_at)
            self.next_at = at + self.gap
        if at > now:
            self._sleep(at - now)


class LiveQlooClient:
    mode = "live"

    def __init__(self, api_key: str, cache_dir: Path, http: httpx.Client | None = None):
        self.cache_dir = cache_dir
        self.http = http or httpx.Client(base_url=BASE_URL, headers={"X-Api-Key": api_key}, timeout=20)
        self.throttle = Throttle(PER_SECOND)

    def get(self, path: str, params: dict) -> dict:
        check_params(path, params)
        f = self.cache_dir / f"{cache_key(path, params)}.json"
        if f.exists():
            return json.loads(f.read_text())
        for attempt in range(2):  # one bounded retry (SPEC §6)
            self.throttle.wait()
            try:
                r = self.http.get(path, params=_wire(params))
            except httpx.TimeoutException:
                continue
            if r.status_code == 429:
                time.sleep(1.1)  # the per-second window resets after 1s
                continue
            if r.status_code == 404:
                return {"success": True, "results": []}
            if r.status_code == 400:
                try:
                    msg = "; ".join(e.get("message", "") for e in r.json().get("errors", []))
                except ValueError:
                    msg = r.text[:200]
                raise QlooBadRequest(msg or "bad request")
            r.raise_for_status()
            if (left := r.headers.get("x-month-ratelimit-remaining")) and int(left) % 250 == 0:
                log.info("Qloo monthly quota remaining: %s", left)
            body = r.json()
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps(body))
            return body
        raise QlooUnavailable(f"Qloo unavailable for {path}")


class ReplayQlooClient:
    mode = "replay"

    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir

    def get(self, path: str, params: dict) -> dict:
        check_params(path, params)
        f = self.cache_dir / f"{cache_key(path, params)}.json"
        if not f.exists():
            raise QlooUnavailable(f"not in replay cache: {path}")
        return json.loads(f.read_text())


def make_client(mode: str | None = None) -> QlooClient:
    mode = mode or os.environ.get("QLOO_MODE", "fixture")
    cache = Path(os.environ.get("QLOO_CACHE_DIR", ".qloo-cache"))
    if mode == "live":
        return LiveQlooClient(os.environ["QLOO_API_KEY"], cache)
    if mode == "replay":
        return ReplayQlooClient(cache)
    from fanfit.fixture import FixtureQlooClient

    return FixtureQlooClient()
