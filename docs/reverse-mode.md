# Plan: Reverse mode (creator → brands)

**Status:** SHIPPED 2026-10-13 (commit 8396436)

## Use cases
- **Creator / talent manager** (an indie band, a podcast, a show, a creator): "Which brands should I pitch, and what do I put in the pitch?"
- **Headline scenario:** pick the "Huberman Lab" example → FanFit ranks brands whose customers over-index on Huberman Lab's audience
  (live spike: Whoop, Four Sigmatic, Huel, Oura Ring), each card with Qloo evidence, grounded "why this fit" lines,
  a one-click email *from the creator to the brand*, and the AI-alone comparison.

## Design
- Same engine, other direction. `Brief.subject_type` (default `"brand"`) names what `Brief.brand` is; reverse mode sets it to
  artist / podcast / tv_show / person and `partner_types=["brand"]`. `resolve()` searches `urn:entity:<subject_type>`.
  `/v2/insights filter.type=urn:entity:brand` + the creator entity + age + market does the ranking (verified live, below).
- Brand cards: drop `business_model: Nonprofit` (charities aren't sponsors). Evidence adds Qloo's
  `aspirational_lifestyle` themes (shown as the "customers are into" chips) and its `audience_identity` sentence.
  Brand tags are skipped: many are Wikipedia categories ("1920 establishments in Washington").
- Prompts (claims, pitch, AI-alone) take the direction, so the email is written from the creator to the brand.
- UI: a "I'm a brand / I'm a creator" switch. Creator mode has its own examples and a short form (name, type, age, market).
  **Free-text briefs stay brand-side only** (the agent's tools search brands); creator mode says so.
- Rejected: a separate pipeline/endpoint set (duplicates resolve/shortlist/compare/pitch for one parameter).

## Phases
- [x] Phase 0 — spike on live Qloo (4 creators): sensible brands, `properties` carry brand_type / business_model /
      audience_identity / aspirational_lifestyle; nonprofits appear (Trevor Project, NOH8) → filter.
- [x] Phase 1 — pipeline: `subject_type`, brand partners, nonprofit filter, brand evidence. Tests first.
- [x] Phase 2 — prompts: direction-aware claims, pitch and AI-alone baseline. Tests first.
- [x] Phase 3 — web + UI: creator presets, form, labels; `/api/config` lists both preset sets.
- [x] Phase 4 — live check in Chrome, warm the cache (replay), deploy, README/Devpost.

## Test plan
- TDD (fixtures/stubs): resolve searches the subject type; brand partners come back as cards; nonprofits dropped;
  lifestyle + identity become citable evidence; prompts carry the direction; reverse presets resolve and shortlist.
- Verification-after: live presets in Chrome; `warm_cache.py live` then `replay` covers the new examples.

## Risks
- Qloo quota: 4 creator examples ≈ 60 calls to warm. Fine (≈9,400 left).
- Popular mega-brands could dominate: not seen in the spike (affinity, not popularity, drives the order).

## Progress log
- 2026-10-13: spike done (see Phase 0). Wrong earlier assumption from `docs/datacheck.md` ("brands have no tags"):
  brand results do carry tags and rich `properties`.
- 2026-10-13: shipped. 67 tests. Verified in Chrome (desktop, dark; 400 px headless): creator examples, email, compare,
  brand mode unchanged. Deployed; the 4 creator examples warmed live and replayed with no key (14/14). Brand-side saved
  AI-alone files kept their names (test added): still 3 of 72. Creator side: 3 of 32. Known limit: the email can still
  add colour about the creator ("Khruangbin's music evokes…") inside a cited point; the validator checks citations, not that.
