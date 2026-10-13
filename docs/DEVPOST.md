# Devpost submission draft: FanFit

Paste-ready sections for the Qloo Agentic Hackathon submission form. Numbers are from live Qloo runs on 2026-10-13 (`docs/datacheck.md`).

---

## Project name
FanFit

## Tagline (under 200 characters)
Sponsorship partners whose fans already love your brand. An agent ranks artists, podcasts, shows and creators by real Qloo taste affinity, and shows its evidence.

## Links
- **Live demo (no login):** https://agenticai-fanfit.brainupgrade.in
- **Code:** https://github.com/brainupgrade-in/fanfit

## Inspiration
Sponsorship is a huge market, and partners are still chosen mostly by follower counts. Reach tells you how many people will see your logo, not whether they'll care. We asked an LLM "which podcasts should sponsor our hot sauce?" and got the same stereotypes you'd guess yourself. That's the gap Qloo's taste graph fills: it knows what audiences actually love, across music, podcasts, TV and brands.

## What it does
- **Brief → agent → Qloo entities.** Describe a campaign in plain English. A Nemotron agent looks up the brand and 1–3 taste words in Qloo with tools, retries short variants when a search misses, and can only use IDs Qloo returned. You confirm the entities before anything is ranked.
- **Ranked partners with evidence cards.** Qloo Insights ranks artists, podcasts, TV shows and creators by affinity with the brand's taste signal, filtered to your age band. Each card shows:
  - the affinity score;
  - shared taste tags;
  - the share of the audience in your age band;
  - regions with the strongest affinity;
  - a 6-month trend.
- **Grounded "why this fit."** Every AI-written line cites the card evidence it rests on, and a validator removes anything that doesn't. Hover a citation to see the exact data behind it.
- **One-click outreach email.** It's built only from evidence that supports the deal, with every fact cited.
- **"Would AI alone get this right?"** The same brief and the same model, without Qloo. FanFit checks each of the AI's picks against Qloo and shows where Qloo ranks them, plus the partners only FanFit found. On our three live presets, **none of the AI's 18 picks made FanFit's top 8**. For Patagonia's tour, the AI picked The Lumineers (Qloo rank #13 for the brief) and Maggie Rogers (#15). Qloo's top picks were Houndmouth, Caamp and Mt. Joy, whose audiences over-index on Patagonia and with 30–34 year olds.

## How we built it
- **Qloo:**
  - `/search` and `/v2/tags` turn the brief into a signal;
  - `/v2/insights` with `filter.type` = artist / podcast / tv_show / person, the brand entity plus taste tags as signals, and the age band, produces the ranking;
  - the target market goes in as `signal.location.query`, and `urn:demographics` gives the age profile as an over/under-index.
- **Agent:** an LLM tool-calling loop (search_brand, search_tags, finish) on **NVIDIA Nemotron 3 Super** via **Nebius Token Factory**, called through any OpenAI-compatible endpoint. We compared three Nemotron models on our own briefs and picked the one that was fastest and whose claims all passed the validator.
- **Grounding:** structured claims with evidence IDs, plus a deterministic validator. It rejects:
  - claims that cite no evidence, or cite evidence that isn't on the card;
  - claims that name other cards' partners;
  - "strong", "high" or "top" without a quoted value;
  - the age affinity index turned into a percentage of the audience.
- **Backend:** FastAPI streams the agent's steps live to the page (NDJSON). Qloo access goes through one client with three modes: fixture, live with a disk cache, and replay, so the demo survives after the key expires. A parameter allowlist means nothing the user types reaches Qloo verbatim.
- **Hosting:** k3s on an NVIDIA DGX Spark behind a Cloudflare tunnel. Plain HTML/JS with no framework. 40+ tests.

## Challenges we ran into
- **Keeping an LLM honest about data.** The model happily turned a regional affinity score into "a large portion of listeners live in Denver", and pitched weak evidence as a strength. Prompting alone didn't fix it; a validator with explicit rules and passing only supportive evidence to the pitch writer did.
- **Building before the API key arrived, then meeting real data.** We built against fixtures behind one Qloo interface. The live check then overturned several assumptions: demographics are −1..1 indices, not shares; the heatmap returns unnamed geohashes; trending was flat; brands have no tags. Because all parsing lived in one file, adapting took hours, not days. Details in `docs/datacheck.md`.
- **Rate limits** (5/s, 10k/month): a thread-safe throttle, 1-second backoff on 429s, and caching every response.
- **Streaming through Cloudflare and ingress-nginx** without buffering, and rate-limiting by the real visitor IP behind two proxies.

## Accomplishments we're proud of
- Every sentence the AI writes on a card or in a pitch is traceable to a Qloo number.
- The "AI alone" comparison makes Qloo's value visible in one click instead of asserting it.

## What we learned
Taste data changes the question from "who is big?" to "whose fans already like what we sell?", and an agent is the right shape for it: resolving fuzzy briefs into entities is the hard part, and it's exactly what tool use is good at.

## What's next
- **Reverse mode:** creators enter their show and get the brands most likely to say yes. Same engine, `filter.type=urn:entity:brand`.
- **Commercial case for Qloo:**
  - **Agencies and talent agencies:** a per-seat workflow product, where each brief drives several Qloo calls.
  - **Creators:** a self-serve tier, a long-tail market Qloo doesn't reach today.
  - **Positioning:** a showcase of Qloo as the evidence layer behind agent decisions.

## Built with
qloo-api, python, fastapi, nvidia-nemotron, nebius-token-factory, kubernetes, k3s, cloudflare, javascript, html, css

## Testing instructions for judges
Open the demo URL; no login. Click any example on the left; results stream in about 10 s. Then:
- hover a citation chip on a card to see its evidence;
- click **Draft outreach email** on a card;
- scroll down and click **Compare with AI alone**.

Or type your own brief in "Describe it". The demo runs on live Qloo data; if the hackathon key is deactivated before judging ends, the three examples are served from cached Qloo responses (a banner says so).
