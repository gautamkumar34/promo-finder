"""Stage 5a — Self-audit critic.

An INDEPENDENT skeptic (default: Opus 5.5, a different/stronger model than the
Sonnet scorer) re-reads the top promos and flags known failure modes. This is
NOT the quality proof on its own — the human 5-episode ground truth is — but it
surfaces bad picks automatically and fills the "flags" the UI shows.

Failure modes:
    melodrama_false_positive - reads shocking on paper, mundane/dream/joke in context
    context_bleed            - confusing jump / needs backstory a scroller won't have
    pacing_mismatch          - leans on reaction-shot timing the script can't capture
    weak_hook                - first ~3s won't actually stop a scroller

Usage:
    python -m src.audit [--bundle raw_outputs/promo_bundle.json]
                        [--top 25] [--provider claude --model claude-opus-5-5]
"""
from __future__ import annotations

import argparse
import json

from .adapter import ModelAdapter

FLAGS = ["melodrama_false_positive", "context_bleed", "pacing_mismatch", "weak_hook"]

SYSTEM = ("You are a skeptical senior promo editor doing QA on auto-selected "
          "microdrama promo clips. You are hard to impress and you call out weak picks.")


def build_prompt(promos: list) -> str:
    blocks = []
    for p in promos:
        blocks.append(
            f"--- RANK {p['rank']} (Ep{p['episode_number']} {p.get('timecode','')}) ---\n"
            f"HOOK: {p['hook_line']}\nCLIFF: {p['cliffhanger_line']}\n"
            f"SCRIPT SPAN:\n{p.get('script_span','')}\n")
    body = "\n".join(blocks)
    return f"""Review these {len(promos)} promo clips. For EACH rank, decide if it
has any of these problems, judging as a stranger scrolling TikTok:

- melodrama_false_positive: a line that reads shocking on paper but is mundane,
  a joke, or a dream/hypothetical in the actual scene context
- context_bleed: a new viewer would be lost — relies on backstory or too many
  named characters introduced with no setup
- pacing_mismatch: the punch depends on a reaction shot / silence / performance
  beat the script timing doesn't capture, so the cut may feel off
- weak_hook: the first ~3 seconds won't actually stop a scroller

Most good promos will have NO flags — only flag real problems. Return ONLY a JSON
array, one object per rank:
[{{"rank": 1, "flags": [], "note": ""}}]
Put a short reason in "note" only when you flag something.

{body}"""


def audit(promos: list, adapter: ModelAdapter) -> dict:
    result = adapter.complete_json(build_prompt(promos), system=SYSTEM)
    if isinstance(result, dict):
        result = result.get("results") or result.get("audits") or [result]
    out = {}
    for r in result:
        if isinstance(r, dict) and "rank" in r:
            flags = [f for f in (r.get("flags") or []) if f in FLAGS]
            out[int(r["rank"])] = {"flags": flags, "note": r.get("note", "")}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", default="raw_outputs/promo_bundle.json")
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--provider", default="claude")
    ap.add_argument("--model", default="claude-opus-5-5")
    ap.add_argument("--out", default=None, help="defaults to overwriting --bundle")
    args = ap.parse_args()

    promos = json.load(open(args.bundle))
    top = promos[:args.top]
    adapter = ModelAdapter(provider=args.provider, model=args.model)
    print(f"auditing top {len(top)} promos with {adapter}…")
    audits = audit(top, adapter)

    flagged = 0
    for p in promos:
        a = audits.get(p["rank"])
        if a:
            p["flags"] = a["flags"]
            p["audit_note"] = a["note"]
            if a["flags"]:
                flagged += 1
        else:
            p.setdefault("flags", [])
    out = args.out or args.bundle
    json.dump(promos, open(out, "w"), ensure_ascii=False, indent=2)
    u = getattr(adapter, "last_usage", {}) or {}
    cost = (u.get("in") or 0) / 1e6 * 4 + (u.get("out") or 0) / 1e6 * 20
    print(f"flagged {flagged}/{len(top)} promos -> {out}  (~${cost:.3f} Opus 5.5)")
    for p in top:
        if p.get("flags"):
            print(f"  #{p['rank']} Ep{p['episode_number']}: {', '.join(p['flags'])} — {p.get('audit_note','')[:80]}")


if __name__ == "__main__":
    main()
