# FanFit — spec

Sponsorship matchmaking agent grounded in Qloo's taste graph.
v1 written 2026-10-13. v2 2026-10-13, after an independent spec review (all 12 points applied; see §14).
Status: checked against live Qloo on 2026-10-13. Verdict GO. Where live data changed this design (heatmap, trending and shared tags dropped; demographics are indices; the market is a ranking signal), [`datacheck.md`](datacheck.md) wins over §4–§6 below.

## 1. Problem
Brands choose sponsorship partners (artists, podcasts, creators, TV shows) mostly by reach (followers, downloads) and gut feel.
Reach says nothing about whether *those fans like this kind of brand*, so a lot of sponsorship money is spent on audiences that don't fit.
On the other side, independent creators don't know which brands to pitch, and they have no evidence to put in a pitch.
A plain LLM answers "who should sponsor X?" with stereotypes ("energy drinks for gamers"). It has no affinity data.

## 2. Users, and why this helps Qloo
- **Primary: a brand or agency marketer** planning a campaign. Needs a defensible shortlist of partners, quickly.
- **Secondary (stretch): a creator or talent manager** looking for brands to pitch.

**What's new compared with Qloo's own products.** Qloo already sells audience insight to enterprise brands and agencies, as data and dashboards.
FanFit is a different layer: an *agent* that turns a plain-English brief into a ranked partner shortlist and a ready-to-send pitch,
and shows its evidence. That is the decision a sponsorship buyer actually has to make.
**Commercial case for Qloo:** (1) it opens a workflow product for the sponsorship and partnerships market, sold per seat to agencies and talent agencies, with every brief driving several API calls;
(2) the creator side reaches a long tail of buyers Qloo does not serve today (podcasters, independent artists), as a cheap self-serve tier;
(3) it shows Qloo as the evidence layer behind agent decisions, which is the position Qloo wants in an agent-driven market.

## 3. Scope
### Must ship
**Flow A, brand → partners**
1. The user enters a brief: brand (or category words if the brand isn't in Qloo), target age band, gender (optional), target market (optional), and partner types (artist / podcast / tv_show / person).
2. The agent pulls **short lookup terms** out of the brief (brand name, 1–3 category words) and resolves them with Qloo search and tags.
   It **shows what it resolved** ("Brand: X (Qloo entity). Tags: cold brew, specialty coffee"), and the user confirms or corrects before continuing.
   Preset briefs come with their entities already confirmed, so a judge gets a one-click run.
3. The agent fetches candidates per partner type using Qloo Insights, signalled by the brand and tags and filtered to the demographic band.
   It caps the shortlist at **8 cards**.
4. Each **fit card** shows:
   - the affinity score and rank (Qloo);
   - the top regions for that partner's audience, as a ranked list compared with the target market (Qloo heatmap). No map;
   - a trend badge, **only if** the §9 check shows trending data exists for that type;
   - the shared taste tags (Qloo explainability, or the partner's own tags);
   - a *why this fit* paragraph built from **structured claims, each tied to an evidence id on the card** (§5). It is labelled as AI interpretation.
5. **Draft pitch:** a one-page outreach email built only from the card's evidence.
6. **Qloo vs. LLM-only panel** (§5.4).
7. **3 preset briefs** on the landing page. One of them is an artist and tour sponsorship brief, because a Live Nation executive is on the judging panel.

### Stretch (only after everything in "must ship" works on the live URL)
- **Reverse button** (creator → brands). It reuses the flow A card code with `filter.type=urn:entity:brand`, signalled by the creator's entity.
- Markdown export of the shortlist.

### Cut
Compare view, PDF export, maps.

## 4. Qloo usage (decision: plain REST from Python, no `qloo mcp`)
**Why REST:** a single `QlooClient` keeps caching, replay mode and the "no free text" rule in one place.
The official harness (`@qloo/qloo-harness` 0.1.26, read but not run) is used only as a reference for request shapes. Its query patterns are copied below.

| Step | Request |
|---|---|
| Resolve the brand or a named partner | `GET /search?query=<lookup term>&types=urn:entity:brand` (or another type) |
| Category words → tag ids | `GET /v2/tags?filter.query=<word>` (exact parameter name to verify) |
| Candidate partners | `GET /v2/insights` with `filter.type=urn:entity:{artist,podcast,tv_show,person}`, `signal.interests.entities=<brand id>`, `signal.interests.tags=<tag ids>`, `operator.signal.interests.tags=union`, `signal.demographics.age=<band>`, `signal.demographics.gender=<g>`, `feature.explainability=true`, `take=20` |
| Audience geography for a partner | `GET /v2/insights` with `filter.type=urn:heatmap`, `signal.interests.entities=<partner id>`, `filter.location.query=<target market>`, sorted by `query.affinity` |
| Audience demographics (card detail) | `GET /v2/insights` with `filter.type=urn:demographics`, `signal.interests.entities=<partner id>` |
| Momentum badge | `GET /v2/trending` with `filter.type`, `signal.interests.entities`, `filter.start_date`, `filter.end_date` |
| Reverse (stretch) | `GET /v2/insights` with `filter.type=urn:entity:brand`, `signal.interests.entities=<creator id>` |

Base URL `https://hackathon.api.qloo.com`, header `X-Api-Key`. Affinity is read from `entity.affinity`, falling back to `entity.query.affinity`, as the harness does.
Age bands come from the documented set: `24_and_younger`, `25_to_29`, `30_to_34`, `35_to_44`, `45_to_54`, `55_and_older`.

## 5. Agent design
### 5.1 Where the agent loop is (revised 2026-10-13 during the build)
- **Resolution is the agent loop.** An LLM tool-calling loop (`search_brand`, `search_tags`, `finish`) turns a free-text brief into Qloo ids.
  It retries short variants when a search misses, and picks between ambiguous matches.
  `finish` accepts **only ids the agent actually received from Qloo** in that run, and the UI then asks the user to confirm.
  Limit: 12 tool calls.
- **Shortlisting is fixed code, not LLM-driven.** It runs the insights call per partner type, then the heatmap, demographics and trending calls for the top 8.
  This keeps the demo predictable and the number of Qloo calls bounded.
- **The LLM comes back for** `write_claims` (validated, §5.3) and `draft_pitch`.
- **Presets skip the agent** and use structured briefs, so they run without an LLM.

### 5.2 The QlooClient interface
One interface with two implementations:
- **`FixtureQlooClient`:** serves recorded or synthetic JSON from `fixtures/`. Used for development before the key arrives, and for tests.
- **`LiveQlooClient`:** uses httpx, and writes every response to a disk cache keyed by (path, sorted params).
  A third mode, **replay**, serves only from that cache and shows a "cached Qloo data" banner in the UI.

The mode is set by `QLOO_MODE=fixture|live|replay`. Switching from fixtures to the live API changes no app code.

### 5.3 Grounding (testable)
`write_claims` returns structured output, a list of `{text, evidence_ids[]}` objects.
Each `evidence_id` points to a field on the card, such as `affinity`, `tag:<tag id>`, `geo:<region>`, `demo:<band>` or `trend`.
A validator **drops any claim** that has no evidence id, an unknown id, or names an entity or tag that isn't on the card.
The UI shows only the claims that pass, each linked to its evidence.

### 5.4 Qloo vs. LLM-only
The comparison run uses the **same brief and the same model, with no tools**.
The panel shows:
- (a) the partners that only Qloo found;
- (b) Qloo affinity scores, which the LLM-only side cannot give;
- (c) partners the LLM-only side named that Qloo rates low, or can't resolve.

Presets are chosen where the difference is large: niche brands and non-obvious partners.

### 5.5 LLM provider
Reached through an OpenAI-compatible client, configured by `LLM_BASE_URL`, `LLM_API_KEY` and `LLM_MODEL`.
- **Primary:** a Nemotron model on Nebius Token Factory.
- **Fallback:** LiteLLM. The fallback must be *deployed and tested*, not just configured.

The app must work if either provider is down.

## 6. Product and UI
- A one-page web app. On the left, the brief form and the 3 presets. On the right, the live agent step trace, the confirmation step, then the cards and the vs. panel.
- **States:**

| State | What the user sees |
|---|---|
| Loading | Step trace with a spinner per step |
| Unresolved brief | "Couldn't find '<term>' in Qloo. Try the category instead." with the tag suggestions |
| Empty result | Message naming the filter to relax (age band, partner type) |
| Qloo 429 or timeout | One bounded retry, then a fallback to replay cache if it has the request, otherwise a clear error |
| LLM failure | Cards still render with the Qloo evidence only; the "why" text and pitch are hidden |
| Replay mode | Persistent banner |

- **Abuse limits** (the demo is public with no login): a per-IP rate limit (for example 10 briefs an hour), a global daily cap on live Qloo and LLM calls, and the 8-card cap.
  When the cap is hit, the app falls back to replay mode for presets.

## 7. Stack and hosting
- Python 3.12, FastAPI, httpx, uv. The agent loop is hand-written; LangGraph only if the loop gets messy.
- Frontend: one HTML page served by FastAPI (plain JS or HTMX). No build pipeline.
- A container on Spark k3s, exposed through the Cloudflare tunnel at a public URL.
  This deployment is excluded from the cohort scale-down of the training sandboxes.
- An uptime monitor checks the URL until 16 Nov.
- Secrets stay server-side only.

## 8. Data handling
- **Nothing the user types goes to Qloo verbatim.** Qloo only ever receives:
  - (a) short lookup terms for `/search` and `/v2/tags`, which the agent extracts and caps at 40 characters each;
  - (b) Qloo entity ids and tag ids;
  - (c) demographic bands from the fixed enum;
  - (d) a market name for `filter.location.query`.

  `QlooClient` enforces this with a parameter allowlist, and a unit test covers it.
- Lookup terms must resolve to a **public Qloo entity**. If a name doesn't resolve, the UI says so and nothing else is sent. There is no "describe a person" input.
- Results are aggregate affinities. The UI says so, and makes no claims about individuals.
- **Fixtures in the public repo:** synthetic, or trimmed to the fields we use, until the Qloo terms on redistributing responses are checked.
  The live replay cache stays out of git (it's on the deployed volume).

## 9. Day-1 data check (go / no-go)
Run `scripts/datacheck.py` with the key, over 5 brands from different categories:
1. **Brand coverage:** 4 of 5 brands resolve with `/search` `types=urn:entity:brand`.
2. **Partner types:** insights returns at least 10 results for each of artist, podcast, tv_show and person, using a brand signal.
3. **Qloo adds signal:** for each brand, compare the top 10 with the brand signal against the top 10 with no signal (popularity baseline).
   The mean Jaccard overlap must be **below 0.5**, and at least 3 of 5 rankings must pass a manual gut check (recorded in `docs/datacheck.md`).
4. **Optional data:** do heatmap, demographics and trending return data for the partner types? This decides whether those parts of the card ship.

**Fallbacks:** if brands are thin, use category tags as the signal (rerun 3 with tags). If that's thin too, pivot to the tour and pop-up planner (artists + places).

## 10. Acceptance criteria
- [ ] The live public URL runs flow A end to end, with no login, for all 3 presets.
- [ ] Each preset finishes in **under 20 s** from a cold cache, and in under 5 s in replay mode.
- [ ] Every "why" claim shown has at least one valid evidence id. A validator unit test passes on the preset outputs, plus negative cases (an invented tag, a missing id).
- [ ] A unit test shows no Qloo request carries parameters outside the allowlist. Free-text params (`query`, `filter.query`, `filter.location.query`) must be 40 characters or fewer; id params must match the id/urn pattern; enums must be from the fixed lists.
- [ ] The Qloo vs. LLM-only panel works on all presets and shows at least one partner only Qloo found in each.
- [ ] The demo works with `QLOO_MODE=replay` and no `QLOO_API_KEY`, and with either LLM provider.
- [ ] The UI handles each §6 state (each covered by a test with the fixture client).
- [ ] An uptime monitor is on the URL.
- [ ] The public GitHub repo shows Apache-2.0 in its About section. The README covers setup, how Qloo is used, a redacted request → result walkthrough, the limitations and the commercial case.
- [ ] The Devpost description and screenshots are done.

## 11. Milestones (deadline Sat 31 Oct 09:15 IST; Agenthon finals run 13–25 Oct at the same time)
| Date | Milestone |
|---|---|
| 13 Oct | Key requested. Spec v2. Fixture-driven build starts. |
| **16 Oct** | No key yet → escalate in Discord #api-help. |
| 18 Oct | With fixtures: QlooClient (fixture + live + replay), agent loop, claims validator, fit-card JSON from the CLI. |
| **19 Oct** | **Go / pivot decision.** Uses the §9 check if the key is in; otherwise go, on the strength of the API reference, which lists brand, podcast, person and tv_show as types. |
| 22 Oct | Web UI: trace, confirmation, cards, all §6 states. |
| 24 Oct | Deployed on the public URL. vs. panel working. Replay cache seeded with the presets. |
| 27 Oct | Polish, pitch drafting, README, uptime monitor. Stretch work only if all of this is done. |
| 29 Oct | Devpost submission saved as a draft. |

## 12. Risks
- **Key arrival:** handled by building on fixtures, the dated escalation and the 19 Oct decision.
- **Key turned off before judging ends (16 Nov):** ask in Discord, in writing, when the key is turned off. Replay mode covers the presets regardless.
- **LLM credits or outage:** a deployed fallback provider, and cards degrade to evidence only.
- **Entity coverage:** §9, with fallbacks.
- **The vs. panel backfires:** chosen presets and a defined comparison (§5.4).
- **Quota or abuse:** caching, rate limits, the daily cap, and replay fallback.
- **Spark uptime:** excluded from the sandbox scale-down, and watched by the uptime monitor.
- **Also entering Nebius:** allowed by Qloo's rules. Confirm the Nebius rules allow a project entered elsewhere.
  The README makes clear that Qloo is the core. The Nebius requirement must not make the Qloo demo fragile (fallback provider).

## 13. Open items
- Heatmap `filter.location.query` limits results to *within* the market (harness semantics). Decide on live data whether the card should show national regions (no filter) or neighbourhoods within the target market.
- The exact parameter name of `/v2/tags` for text search, and the response fields. Verify with the key.
- Whether to redistribute Qloo responses as fixtures (ask in Discord).

## 14. Review log
2026-10-13, independent spec review (spec-analyst subagent) produced 12 points:
1. Replay mode for when the key expires → §5.2, §12
2. Scope cut → §3
3. Dated milestones and the fixture client → §5.2, §11
4. Testable grounding → §5.3
5. Enforced privacy → §8. Adjusted: search needs lookup terms, so the rule is "only short extracted terms", not "no text at all".
6. REST vs. MCP decision → §4
7. Measurable go/no-go → §9
8. Defined vs. panel → §5.4
9. Commercial case and the Live Nation preset → §2, §3
10. UX states and abuse limits → §6
11. Fixtures and redistribution → §8
12. Nebius dual entry → §12
