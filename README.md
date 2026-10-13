# qloo-devpost

Entry for the [Qloo Agentic Hackathon](https://qloo.devpost.com/) ("Agents, but with taste").

> Project name, problem statement and demo link: TBD.

## Setup

```bash
uv sync
cp .env.example .env && chmod 600 .env   # add QLOO_API_KEY
uv run scripts/smoke.py "Agatha Christie"     # live API check
uv run pytest -q                               # tests (fixture mode, no keys needed)
uv run python -m fanfit --preset cold-brew     # fit-card JSON; presets: cold-brew, trail, tour
uv run uvicorn fanfit.web:app --reload        # web app on http://127.0.0.1:8000
```

`QLOO_MODE=fixture` (default, fictional data in `fixtures/world.json`) | `live` (needs `QLOO_API_KEY`, caches to `.qloo-cache/`) | `replay` (cache only).
Set `LLM_BASE_URL`, `LLM_API_KEY` and `LLM_MODEL` (any OpenAI-compatible endpoint) to enable the free-text agent (`--text`) and the "why this fit" claims.

## How Qloo is used

TBD: which Qloo endpoints/workflows, why they fit, and a redacted request-to-result walkthrough.

## Known limitations

TBD. Qloo results describe aggregate taste affinities, not an individual's preferences.

## License

Apache-2.0, see [LICENSE](LICENSE).
