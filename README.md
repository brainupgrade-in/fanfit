# FanFit

**Sponsorship partners whose fans already love your brand, ranked by real taste data from Qloo, not follower counts.**

Live demo: **https://agenticai-fanfit.brainupgrade.in** (no login) · Built for the [Qloo Agentic Hackathon](https://qloo.devpost.com/)

> Runs on **live Qloo data** (hackathon API). The three examples on the page are real brands: Patagonia, Glossier, Oatly.

## The problem

Brands pick sponsorship partners (artists, podcasts, shows, creators) mostly by reach and gut feel. Reach says nothing about whether *those fans like this kind of brand*. Ask a plain LLM "who should sponsor X?" and you get stereotypes ("energy drinks for gamers"), because it has no affinity data. Independent creators have the mirror problem: they don't know which brands to pitch, or what evidence to put in the pitch.

## What FanFit does

1. **You describe a campaign** in plain English, or fill in a short form, or pick an example.
2. **An agent turns the brief into Qloo entities.** It looks up the brand and 1–3 category words with tools. It never sends your whole brief, and it retries short variants when a search misses. It can only use IDs Qloo actually returned.
3. **You confirm** what it resolved ("Brand: Ember & Ash Hot Sauce · Taste tag: street food"). Remove anything that's off.
4. **FanFit ranks partners by Qloo taste affinity** for that brand (plus any taste tags), your age band and your market. It builds an evidence card for the top 8:
   - affinity score and rank;
   - Qloo's taste tags for the partner's audience ("their audience is into…");
   - how strongly the audience over- or under-indexes with your target age band (a −1 to 1 index, not a share);
   - the market the ranking was computed for.
5. **"Why this fit" lines** are written by an LLM but **each one cites the evidence it rests on**. A validator drops any line that cites nothing, cites evidence not on the card, or names another card's partner or tags. It also drops any line that says "strong", "high" or "top" without quoting the value, or that turns the age index into a percentage of the audience. Hovering a citation highlights that evidence.
6. **"Draft outreach email"** writes a pitch to the partner. Every fact in the email is an evidence-cited point, and it only uses evidence that argues *for* the deal (an under-indexed age band is never sold as a strength).
7. **"Would AI alone get this right?"** runs the same brief through the same model with no Qloo access. It then checks each of its picks in Qloo (in FanFit's shortlist / Qloo ranks it low / not a fit / not found) and lists the partners only FanFit found.

## How Qloo is used

| Step | Qloo API call | Why |
|---|---|---|
| Resolve the brand | `GET /search?query=<brand>&types=urn:entity:brand` | Entity ID to use as the taste signal |
| Category words → taste tags | `GET /v2/tags?filter.query=<word>` | An extra signal, or the only one when the brand isn't in Qloo |
| Rank partners | `GET /v2/insights` with `filter.type=urn:entity:{artist,podcast,tv_show,person}`, `signal.interests.entities=<brand>`, `signal.interests.tags=<tags>`, `signal.demographics.age=<band>`, `signal.location.query=<market>` | The core ranking: whose audience over-indexes on this brand's taste, for this age band and market |
| Audience age profile | `GET /v2/insights` with `filter.type=urn:demographics` | Is the partner's audience over-indexed with the target band (−1..1) |
| Check AI-alone picks | `GET /search` per suggested name | Shows what an LLM picks without taste data, and where Qloo ranks those picks |

Base URL `https://hackathon.api.qloo.com`, header `X-Api-Key`. What we learned from the live API (and what we dropped: heatmap, trending) is in [`docs/datacheck.md`](docs/datacheck.md).

**Request → result (live, Patagonia preset).** Brief: *"Patagonia wants to sponsor a music tour… 30–34 year olds, Denver."*

```text
/search      query="Patagonia" types=urn:entity:brand                     → Patagonia (exact match)
user confirms the brand
/v2/insights filter.type=urn:entity:artist signal.interests.entities=<Patagonia>
             signal.demographics.age=30_to_34 signal.location.query=Denver take=20
                                                                          → 20 artists, best first
/v2/insights filter.type=urn:demographics signal.interests.entities=<artist>   (× top 8)
card #1  Houndmouth (artist), affinity 0.98, over-indexes with 30–34 (+0.56), ranked for Denver,
         audience is into: American Life, Vintage, Harmonic …
         why (LLM, varies per run), e.g. "Its audience over-indexes with 30–34 year olds (+0.56)." [cites demo:30_to_34]
AI alone (same model, no Qloo): The Lumineers → Qloo rank #13, Maggie Rogers → #15, four others outside the top 20
```

## Guardrails

- **Nothing you type goes to Qloo verbatim.** `QlooClient` enforces a parameter allowlist: free-text params are limited to 40 characters, IDs must match the ID/URN pattern, and age and gender come from fixed lists. Unit tests cover this. No personal data is ever sent.
- **Qloo results are aggregate affinities**, not facts about individuals. The UI says so, and AI text is labelled as interpretation.
- **Public demo protection:** a per-visitor hourly limit (keyed on Cloudflare's `CF-Connecting-IP`) and a global daily cap. Qloo and model text is rendered with `textContent` only.
- **Degrades gracefully:** if the LLM is down, cards still show the full Qloo evidence. Qloo timeouts and 429s are retried once, then reported clearly.

## Architecture

```text
browser (plain HTML/JS, NDJSON stream of agent steps)
   │
FastAPI (fanfit/web.py) ── rate limiter
   ├─ agent.py     LLM tool loop: brief → Qloo ids · claims · pitch · AI-alone baseline
   ├─ pipeline.py  resolve → rank_pool → shortlist → evidence cards  (all Qloo parsing lives here)
   ├─ grounding.py claim/pitch validator
   └─ qloo.py      QlooClient: fixture | live (disk cache, 4 req/s throttle, 429 backoff) | replay (cache only, survives key expiry)
```

LLM: **NVIDIA Nemotron 3 Super** (`nvidia/nemotron-3-super-120b-a12b`) on **Nebius Token Factory**, through any OpenAI-compatible endpoint (`LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`). It was chosen over Nemotron Nano and 3.5 Lightning on our own runs: fastest end to end, and every claim passed the validator.

## Run it

```bash
uv sync
cp .env.example .env && chmod 600 .env      # add keys (see below)
uv run pytest -q                             # 40+ tests, no keys needed (fixture mode)
uv run uvicorn fanfit.web:app --reload       # http://127.0.0.1:8000
uv run python -m fanfit --preset cold-brew   # CLI: fit-card JSON (presets: cold-brew, trail, tour)
uv run python -m fanfit --text "your brief"  # CLI with the free-text agent (needs LLM_*)
```

| Variable | Meaning |
|---|---|
| `QLOO_MODE` | `fixture` (default: fictional data in `fixtures/world.json`) · `live` (needs `QLOO_API_KEY`, caches to `QLOO_CACHE_DIR`) · `replay` (cache only) |
| `QLOO_API_KEY` | Hackathon Qloo key (server-side only) |
| `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` | Any OpenAI-compatible endpoint. Without them, the app runs with evidence-only cards |
| `RATE_PER_IP_HOUR`, `RATE_GLOBAL_DAY` | Demo limits (default 20 and 150). Qloo allows 10,000 calls/month; a fresh brief costs about 15, a cached preset 0 |

Deploy (k3s on an arm64 host, no registry): `APP_HOST=<host> deploy/deploy.sh`. It builds on the host, imports into containerd, and applies `deploy/k8s/fanfit.yaml`.

## Status

- ✅ Live Qloo data, real-brand presets, agent, evidence cards, grounding validator, pitch drafting, AI-alone comparison, public deployment, uptime monitoring
- A fresh brief takes about 13–18 s end to end (Qloo about 4.5 s, the rest is LLM claims); a cached preset about 10 s.
- After the hackathon key expires, the deployment switches to `QLOO_MODE=replay`: the cached presets keep working, while uncached free-text briefs get a clear message.

## Known limitations

- Qloo affinity is an aggregate taste signal. It doesn't predict sponsorship ROI, and it says nothing about any individual fan.
- Partner reach, pricing and availability are out of scope; FanFit answers *fit*, not *deal terms*.
- The rate limiter is in memory, so the deployment is single-replica.

## License

Apache-2.0, see [LICENSE](LICENSE).
