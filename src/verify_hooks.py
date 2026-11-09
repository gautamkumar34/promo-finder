"""Deterministic hook-grounding check (code, no LLM).

A promo's `hook_line` is the line meant to stop a scroll in the first ~3s. When
that line is *quoted dialogue*, it should actually appear inside the clip's
window. This check extracts the quoted part of each hook_line and verifies it is
present in the promo's `script_span`. Pure-action hooks (no quotes, e.g. "Thug
shoves Juliana") are skipped on purpose — they describe a visual beat and make
no claim to verbatim dialogue.

It runs from the bundle alone (no screenplay pack needed), so it is reproducible
from the public repo. It only *adds* a boolean `hook_in_span` field to quoted
hooks; it never changes a timestamp, score, rank, wave or existing flag.

    python -I src/verify_hooks.py            # report only (writes nothing)
    python -I src/verify_hooks.py --apply    # add hook_in_span to the bundle
"""
import json
import re
import sys

BUNDLE = "raw_outputs/promo_bundle.json"


def _norm(s: str) -> str:
    s = (s.replace("’", "'").replace("‘", "'")
          .replace("“", '"').replace("”", '"').replace("…", "..."))
    s = re.sub(r"[^a-z0-9' ]+", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def _quotes(hook: str):
    return re.findall(r'[\"“]([^\"“”]+)[\"”]', hook or "")


def hook_in_span(hook_line: str, script_span: str):
    """True/False if the hook has quoted dialogue; None if it's a pure-action hook."""
    quotes = _quotes(hook_line)
    if not quotes:
        return None
    span = _norm(script_span)
    for q in quotes:
        nq = _norm(q)
        if len(nq) < 4:
            continue
        if nq in span:
            continue
        words = nq.split()  # tolerate minor edits: a solid 6-word chunk is enough
        if any(" ".join(words[i:i + 6]) in span for i in range(0, max(1, len(words) - 5))):
            continue
        return False
    return True


def main():
    apply = "--apply" in sys.argv
    data = json.load(open(BUNDLE))
    checked = missed = 0
    for p in data:
        verdict = hook_in_span(p.get("hook_line", ""), p.get("script_span", ""))
        if verdict is None:
            continue
        checked += 1
        p["hook_in_span"] = verdict
        if verdict is False:
            missed += 1
            print(f"  hook_not_in_span  #{p.get('rank')}  Ep{p.get('episode_number')}  "
                  f"{p.get('hook_line')}")
    print(f"\nquoted hooks checked: {checked} | failed: {missed} | "
          f"pure-action (skipped): {len(data) - checked}")
    if apply:
        json.dump(data, open(BUNDLE, "w"), ensure_ascii=False, indent=2)
        print(f"applied: added `hook_in_span` to {checked} quoted hooks in {BUNDLE}")
    else:
        print("report only — pass --apply to write the field into the bundle")


if __name__ == "__main__":
    main()
