"""CLI: python -m fanfit --preset cold-brew   |   python -m fanfit --text "free-text brief" (needs LLM_* env)

QLOO_MODE=fixture|live|replay selects the Qloo client (default fixture).
"""
import argparse
import json
import sys
from dataclasses import asdict

from dotenv import load_dotenv

from fanfit.agent import OpenAICompatLLM, add_claims, resolve_with_agent
from fanfit.pipeline import resolve, shortlist
from fanfit.presets import presets_for
from fanfit.qloo import make_client


def main() -> int:
    load_dotenv()
    ap = argparse.ArgumentParser(prog="fanfit")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--preset")
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
        presets = presets_for(qloo.mode)
        if args.preset not in presets:
            sys.exit(f"unknown preset for {qloo.mode} mode; choose from: {', '.join(presets)}")
        brief = presets[args.preset]["brief"]
        res = resolve(brief, qloo)
    if not res.brand and not res.tags:
        print(json.dumps({"error": "brief did not resolve", "unresolved": res.unresolved, "trace": trace}, indent=2))
        return 1
    cards = shortlist(res, brief, qloo, trace)
    if llm:
        add_claims(cards, res.brand["name"] if res.brand else ", ".join(t["name"] for t in res.tags), llm)
    print(json.dumps({"brief": asdict(brief.clean()), "resolution": asdict(res), "cards": cards, "trace": trace}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
