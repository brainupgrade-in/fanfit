# FanFit — spec

Sponsorship matchmaking agent grounded in Qloo's taste graph. Written 2026-10-13. Status: draft, not yet checked against live API data.

## 1. Problem
Brands choose sponsorship partners (artists, podcasts, creators, TV shows, teams) mostly by reach (followers, downloads) and gut feel.
Reach says nothing about whether *those fans like this kind of brand*, so a lot of sponsorship money is spent on audiences that don't fit.
On the other side, independent creators don't know which brands to pitch, and they have no evidence to put in a pitch.
A plain LLM answers "who should sponsor X?" with stereotypes ("energy drinks for gamers"). It has no affinity data.

## 2. Users
- **Primary: a brand or agency marketer** planning a campaign. Needs a defensible shortlist of partners, quickly.
- **Secondary: a creator or talent manager** (podcaster, musician, show) looking for brands to pitch.

## 3. Core flows
### A. Brand → partners (the main demo)
1. The user types a brief: brand (or a category if the brand isn't in Qloo), product, target audience (age band, gender, optional city/region), and the partner types wanted.
2. The agent resolves the brief into Qloo entities and tags and **shows what it resolved** ("Brand: X, matched by Qloo search. Tags: cold brew, specialty coffee"). The user can correct them before going on.
3. The agent finds candidate partners whose fans have high affinity with the brand and its tags, filtered to the target demographic.
4. It ranks the candidates and builds a **fit card** for each one:
   - affinity score and rank (Qloo);
   - where that audience is concentrated, compared with the target market (Qloo location);
   - whether the partner is rising or falling (Qloo trends, when available);
   - the overlapping taste tags ("fans of both index on: indie folk, specialty coffee, outdoor brands");
   - a one-paragraph *why this fit*, written by the LLM **only from the Qloo evidence on the card**, and labelled as interpretation.
5. The user picks one or more partners. The agent drafts an outreach pitch or a sponsorship one-pager from the fit card evidence.

### B. Creator → brands
The same engine in reverse. The input is the creator's own show or act (a Qloo entity). The output is ranked brands, with fit cards and a pitch email to each.

### C. Compare (stretch)
Two candidate partners side by side, comparing their audiences (demographics, tags, geography), so the user can say "why A over B".

## 4. How Qloo is used (each step must depend on Qloo, not the LLM)
| Step | Qloo call | Notes |
|---|---|---|
| Resolve brand, partner and seed names | `GET /search` | Entity ids. The user confirms ambiguous matches. |
| Category and vibe words → tags | `GET /v2/tags` | Tags become signals when the brand isn't in Qloo. |
| Candidate partners | `GET /v2/insights` with `filter.type` = artist / podcast / tv_show / person, `signal.interests.entities` = brand, `signal.interests.tags`, `signal.demographics.*` | The core affinity ranking. |
| Reverse (creator → brands) | `GET /v2/insights` with `filter.type=urn:entity:brand`, signal = the creator | |
| Where the audience is | `GET /v2/insights` with location signals or filters, or the harness `qloo_where_popular` | Compared with the brief's target market. |
| Audience overlap and differences | harness `qloo_compare_audiences` or the REST equivalent | Shared tags for the fit card. |
| Momentum | harness `qloo_trends` or the REST equivalent | Optional badge. |

Exact parameter names, entity type coverage (brands, podcasts, persons/athletes) and the REST equivalents of the harness workflows **must be verified on day 1 with the key** (see §9).

## 5. Agent design
- **Pattern:** an LLM tool-calling loop. The tools are thin wrappers over the Qloo calls above, plus `render_fit_card` and `draft_pitch`.
  The agent plans the steps, retries when a search is ambiguous, and has to show the user the entities it resolved before ranking.
- **Grounding rule:** every claim on a fit card cites a Qloo field. The LLM may *interpret*, but it may not *invent* affinities.
  Cards visibly separate the Qloo evidence from the AI interpretation.
- **LLM:** reached through an OpenAI-compatible client, so the provider is a config switch. The default is a Nemotron model on Nebius Token Factory (lets the project also enter `~/nebiusglobalaihackathon`). The fallback is any model behind LiteLLM.
- **Caching:** Qloo responses are cached per (endpoint, params) for the demo, to respect quota and keep the demo fast. No bulk crawling.

## 6. Product and UI
- A web app: a brief form or chat on the left, and the agent's live step trace ("resolving brand…", "ranking 40 podcasts…") plus the result cards on the right.
- Fit cards: score bar, a small audience-geography map or list, a trend badge, shared tags, *why this fit*, and a "Draft pitch" button.
- Export a shortlist as Markdown or PDF (stretch).
- 2–3 preset example briefs on the landing page, so judges can try it in one click.

## 7. Stack (assumption, can change)
- Backend: Python 3.12, FastAPI, httpx, uv. The agent loop is hand-written, or LangGraph if the loop gets messy.
- Frontend: one page served by FastAPI (HTMX or a small React bundle). No separate build pipeline unless needed.
- Hosting: a container on Spark k3s behind the Cloudflare tunnel, at a public URL. **It must stay up until 16 Nov.**
- Secrets (`QLOO_API_KEY`, LLM key) stay server-side only.

## 8. Non-goals
- No personal data sent to Qloo (no names of private individuals, emails or location history). Inputs are brands, public entities and demographic bands.
- No follower or reach scraping, and no contract or pricing management.
- No claims about individuals. The results describe aggregate affinities, and the UI says so.

## 9. Day-1 data check (go / no-go for this idea)
Run with the key before building the UI:
1. Do `/search` and `/v2/insights` return **brands**? Try 5 real brands across categories.
2. Does `filter.type` support **podcast**, **artist**, **tv_show**, **person** (athletes/creators) as partner types?
3. Does insights for a brand signal + an artist filter give a plausibly different ranking from the same call with no brand signal? This proves Qloo adds signal.
4. Are location and trend data available for those entity types?

If brands are thin: use category **tags** as the brand signal. If both are thin: pivot to idea #2, the tour and pop-up planner (artists + places).

## 10. Acceptance criteria (for submission)
- [ ] The live public URL works end to end for both flows (A and B), with no login. If login is needed, credentials go in the testing instructions.
- [ ] Each result card shows the Qloo evidence, and the "why" text cites only that evidence.
- [ ] **Qloo vs. LLM-only toggle:** the same brief run without Qloo, shown side by side. This proves the differentiator to judges.
- [ ] The public GitHub repo has an Apache-2.0 license in its About section, and a README with setup steps, how Qloo is used, a redacted request → result walkthrough and the limitations.
- [ ] The Devpost text description and screenshots are done.

## 11. Milestones (deadline Sat 31 Oct 09:15 IST)
| By | Milestone |
|---|---|
| key + 1 day | Day-1 data check (§9) done. Go or pivot. |
| 20 Oct | The Qloo client and agent loop produce ranked fit-card JSON for flow A from the CLI. |
| 24 Oct | Web UI with step trace and cards. Flow B added. |
| 26 Oct | Deployed on the public URL. Qloo vs. LLM-only toggle working. |
| 28 Oct | Polish, preset briefs, README, pitch drafting. |
| 29 Oct | Devpost submission saved as a draft (no last-day risk). |

## 12. Risks
- **Key arrival:** keys are issued by hand. Mitigation: build the UI and the agent loop against recorded fixtures while waiting.
- **Entity coverage:** see §9, with a pivot path.
- **Quota:** caching, and ask in Discord #api-help.
- **Demo uptime to 16 Nov:** Spark sandboxes get scaled down between cohorts. This deployment must be excluded from that.
