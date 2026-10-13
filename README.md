# FanFit

**Sponsorship partners whose fans already love your brand, ranked by real taste data from Qloo, not follower counts.**

Live demo: **https://agenticai-fanfit.brainupgrade.in** (no login) · Built for the [Qloo Agentic Hackathon](https://qloo.devpost.com/)

> ⚠️ **Current status:** the demo runs on **fictional sample data** (banner on the page) until the hackathon Qloo API key arrives. The code paths for live Qloo data are built and tested; see [Status](#status).

## The problem

Brands pick sponsorship partners (artists, podcasts, shows, creators) mostly by reach and gut feel. Reach says nothing about whether *those fans like this kind of brand*. Ask a plain LLM "who should sponsor X?" and you get stereotypes ("energy drinks for gamers"), because it has no affinity data. Independent creators have the mirror problem: they don't know which brands to pitch, or what evidence to put in the pitch.

## What FanFit does

1. **You describe a campaign** in plain English, or fill in a short form, or pick an example.
2. **An agent turns the brief into Qloo entities.** It looks up the brand and 1–3 category words with tools. It never sends your whole brief, and it retries short variants when a search misses. It can only use IDs Qloo actually returned.
3. **You confirm** what it resolved ("Brand: Ember & Ash Hot Sauce · Taste tag: street food"). Remove anything that's off.
4. **FanFit ranks partners by Qloo taste affinity** for that brand, its taste tags and your age band. It builds an evidence card for the top 8:
   - affinity score and rank;
   - shared taste tags;
   - the share of the audience in your target age band;
   - regions with the strongest affinity, with your target market starred;
   - a 6-month trend.
5. **"Why this fit" lines** are written by an LLM but **each one cites the evidence it rests on**. A validator drops any line that cites nothing, cites evidence not on the card, or names another card's partner or tags. It also drops any line that says "strong", "high" or "top" without quoting the value, or that describes regional affinity as where fans live. Hovering a citation highlights that evidence.
6. **"Draft outreach email"** writes a pitch to the partner. Every fact in the email is an evidence-cited point, and it only uses evidence that argues *for* the deal (no 0.5% age share or falling trend as a selling point).
7. **"Would AI alone get this right?"** runs the same brief through the same model with no Qloo access. It then checks each of its picks in Qloo (in FanFit's shortlist / Qloo ranks it low / not a fit / not found) and lists the partners only FanFit found.

## How Qloo is used

| Step | Qloo API call | Why |
|---|---|---|
| Resolve the brand | `GET /search?query=<brand>&types=urn:entity:brand` | Entity ID to use as the taste signal |
| Category words → taste tags | `GET /v2/tags?filter.query=<word>` | A signal when the brand is niche or not in Qloo |
| Rank partners | `GET /v2/insights` with `filter.type=urn:entity:{artist,podcast,tv_show,person}`, `signal.interests.entities=<brand>`, `signal.interests.tags=<tags>`, `signal.demographics.age=<band>`, `feature.explainability=true` | The core ranking: whose audience over-indexes on this brand's taste |
| Regional affinity per partner | `GET /v2/insights` with `filter.type=urn:heatmap` | Where the partner's audience affinity is strongest |
| Audience age profile | `GET /v2/insights` with `filter.type=urn:demographics` | Share of the audience in the target band |
| Momentum | `GET /v2/trending` | Is the partner rising or falling |
| Check AI-alone picks | `GET /search` per suggested name | Shows what the LLM gets wrong without taste data |

Base URL `https://hackathon.api.qloo.com`, header `X-Api-Key`.

**Request → result (redacted, sample data).** Brief: *"Launching Northbound Cold Brew… 25–29 year olds in Austin… artists and podcasts."*

```text
agent → /search          query="Northbound Cold Brew" types=urn:entity:brand   → 1 match
agent → /v2/tags         filter.query="cold brew"                              → tag "cold brew"
user confirms            brand + tag
      → /v2/insights     filter.type=urn:entity:artist  signal.interests.entities=<brand id>
                         signal.interests.tags=<tag id> signal.demographics.age=25_to_29
                         feature.explainability=true take=20                   → 12 artists
      → /v2/insights     filter.type=urn:entity:podcast (same signal)          → 10 podcasts
      → top 8 by affinity, each enriched with heatmap + demographics + trending
card #1  Sol y Brasa (artist), affinity 0.42, shared tags: indie folk, specialty coffee,
         38% of audience aged 25–29
         why (LLM, varies per run), e.g. "Both share a taste for indie folk." [cites tag:indie folk]
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
   └─ qloo.py      QlooClient: fixture | live (disk cache) | replay (cache only, survives key expiry)
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
| `RATE_PER_IP_HOUR`, `RATE_GLOBAL_DAY` | Demo limits (default 20 and 500) |

Deploy (k3s on an arm64 host, no registry): `APP_HOST=<host> deploy/deploy.sh`. It builds on the host, imports into containerd, and applies `deploy/k8s/fanfit.yaml`.

## Status

- ✅ Agent, ranking pipeline, evidence cards, grounding validator, pitch drafting, AI-alone comparison, web UI, public deployment
- ⏳ **Live Qloo data:** waiting for the hackathon API key. Response field names come from Qloo's docs and its official harness, and will be confirmed against live responses; all parsing is in `fanfit/pipeline.py`.
- ⏳ Real-brand presets and a replay cache, so the demo survives key expiry after the deadline.

## Known limitations

- Qloo affinity is an aggregate taste signal. It doesn't predict sponsorship ROI, and it says nothing about any individual fan.
- Partner reach, pricing and availability are out of scope; FanFit answers *fit*, not *deal terms*.
- The rate limiter is in memory, so the deployment is single-replica.

## License

Apache-2.0, see [LICENSE](LICENSE).
