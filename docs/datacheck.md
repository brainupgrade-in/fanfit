# Live Qloo data check (SPEC §9), 2026-10-13

Run with `QLOO_MODE=live uv run scripts/datacheck.py` plus ad-hoc probes. **Verdict: GO with FanFit.**

## Results

| Check | Result |
|---|---|
| 1. Brand coverage | 5/5 brands resolve with an exact name match (Liquid Death, Patagonia, Red Bull, Glossier, Oatly) |
| 2. Partner types | 20/20 results for artist, podcast, tv_show **and** person, for every brand |
| 3. Does the brand signal matter? | Insights can't run without a signal (400), so there is no neutral baseline. Instead we compared brands with each other: the mean top-10 Jaccard overlap between brands is **0.00 for artists** and **0.05 for podcasts** (target < 0.5) |
| Gut check | Patagonia → Bahamas, The Head and the Heart, Lord Huron · Red Bull → Skrillex, Avicii, deadmau5 · Glossier → Clairo, beabadoobee · Oatly → Ben Howard, Rich Roll |
| Market signal | `signal.location.query` re-ranks partners (Glossier podcasts: Austin vs. London lists differ) |

## What live data changed in the design

- **Demographics are affinity indices from −1 to 1, not audience shares.** Cards say "over-indexes with 25–29 (+0.70)". The validator drops share or percentage wording on age evidence.
- **The heatmap needs a location and returns unnamed geohash cells.** City-level output (`output.heatmap.boundary=urn:entity:locality`) returned a 500. So the target market became a **ranking signal** instead of a region list.
- **Trending** was flat or empty for the partners we tested, and `query.measurements.audience_growth` was 0 on all 400 entities. Dropped.
- **Brands carry no tags**, and explainability only reports entity scores for a brand signal. So cards show the **partner's own Qloo taste tags** ("their audience is into…"), not "shared" tags.
- **Limits:** 5 requests/second and 10,000/month. The client throttles to 4/s, backs off for 1 s on a 429, and caches every response. A fresh brief costs about 15 calls; a cached preset costs none.
- **Errors:** an unknown market returns a 400. FanFit then ranks without the location signal and says so.

## AI alone vs. FanFit (live presets)

Same brief, same model (Nemotron 3 Super), no Qloo tools; each AI pick was then looked up in Qloo:

| Preset | AI-alone picks | In FanFit's top 8 | Ranked lower by Qloo for this brief |
|---|---|---|---|
| Patagonia → tour (30–34, Denver) | 6 | 0 | 6 (e.g. The Lumineers #13, Maggie Rogers #15) |
| Glossier → podcasts and creators (<25, LA) | 6 | 0 | 6 (e.g. Emma Chamberlain #10, her podcast #34) |
| Oatly → podcasts and TV (25–29, London) | 6 | 0 | 6 (none in Qloo's top 20 for the brief) |

The AI's picks are reasonable *famous* names. Qloo's picks are the ones whose audiences actually over-index on the brand: Houndmouth, Caamp and Mt. Joy for Patagonia; Devon Lee Carlson and Alexa Demie for Glossier; Jay Shetty and The White Lotus for Oatly.
