"""CLI: python -m fanfit --preset cold-brew   |   python -m fanfit --text "free-text brief" (needs LLM_* env)

QLOO_MODE=fixture|live|replay selects the Qloo client (default fixture).
"""
import argparse
import json
import sys
from dataclasses import asdict

from dotenv import load_dotenv

from fanfit.agent import OpenAICompatLLM, resolve_with_agent, write_claims
from fanfit.pipeline import resolve, shortlist
from fanfit.presets import PRESETS
from fanfit.qloo import make_client


def main() -> int:
    load_dotenv()
    ap = argparse.ArgumentParser(prog="fanfit")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--preset", choices=sorted(PRESETS))
    g.add_argument("--text")
    args = ap.parse_args()

    qloo = make_client()
    llm = OpenAICompatLLM.from_env()
    trace = [f"Qloo mode: {qloo.mode}; LLM: {'on' if llm else 'off (evidence-only cards)'}"]
    if args.text:
        if not llm:
            sys.exit("--text needs LLM_BASE_URL, LLM_API_KEY and LLM_MODEL")
        brief, res = resolve_with_agent(args.text, qloo, llm, trace)
    else:
        brief = PRESETS[args.preset]["brief"]
        res = resolve(brief, qloo)
    if not res.brand and not res.tags:
        print(json.dumps({"error": "brief did not resolve", "unresolved": res.unresolved, "trace": trace}, indent=2))
        return 1
    cards = shortlist(res, brief, qloo, trace)
    if llm:
        label = res.brand["name"] if res.brand else ", ".join(t["name"] for t in res.tags)
        for c in cards:
            c["claims"] = write_claims(c, cards, label, llm)
    print(json.dumps({"brief": asdict(brief.clean()), "resolution": asdict(res), "cards": cards, "trace": trace}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
