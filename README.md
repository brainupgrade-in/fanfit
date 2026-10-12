# qloo-devpost

Entry for the [Qloo Agentic Hackathon](https://qloo.devpost.com/) ("Agents, but with taste").

> Project name, problem statement and demo link: TBD.

## Setup

```bash
uv sync
cp .env.example .env && chmod 600 .env   # add QLOO_API_KEY
uv run scripts/smoke.py "Agatha Christie"
```

## How Qloo is used

TBD: which Qloo endpoints/workflows, why they fit, and a redacted request-to-result walkthrough.

## Known limitations

TBD. Qloo results describe aggregate taste affinities, not an individual's preferences.

## License

Apache-2.0, see [LICENSE](LICENSE).
