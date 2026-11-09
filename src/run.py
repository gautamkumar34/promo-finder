"""Full pipeline runner — one command turns a folder of screenplays into a
ranked, UI-ready promo bundle. This is the "run it again on a new show" entry
point: every stage the offline run used, chained in order.

    python -m src.run <screenplays_dir> [--out bundle.json]
                      [--provider claude --model claude-sonnet-5-5]
                      [--audit-model claude-opus-5-5]
                      [--per-episode 2] [--max 12] [--pairs 6]
                      [--no-stitch] [--no-audit]

Chain: parse -> candidate windows -> LLM score -> cross-episode stitch ->
rank + merge + waves -> script spans -> self-audit -> hook-grounding check.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import time

from .parse import parse_file
from .candidates import generate_candidates
from .score import score_episode
from .stitch import build_index, propose_pairs, validate_pairs, assemble
from .rank import rank, _assign_wave
from .bundle import render_span, _ts
from .audit import audit
from .verify_hooks import hook_in_span
from .adapter import ModelAdapter


def run(directory, provider="claude", model=None, audit_model="claude-opus-5-5",
        per_episode=2, max_candidates=12, pairs=6, do_stitch=True, do_audit=True,
        api_key=None, base_url=None):
    files = sorted(glob.glob(os.path.join(directory, "*.txt")))
    if not files:
        raise SystemExit(f"no .txt screenplays in {directory}")
    parsed = {os.path.basename(p): parse_file(p) for p in files}
    adapter = ModelAdapter(provider=provider, model=model,
                           api_key=api_key, base_url=base_url)

    print(f"[1/6] scoring {len(files)} episode(s) with {adapter}")
    scored = []
    for ep in parsed.values():
        scored.extend(score_episode(adapter, ep, generate_candidates(ep, max_candidates)))
    print(f"      {len(scored)} candidate windows scored")

    cross = []
    if do_stitch and len(parsed) > 1:
        print("[2/6] cross-episode stitch")
        index, lookup = build_index(scored, parsed)
        proposed = propose_pairs(adapter, index, pairs)
        verdicts = validate_pairs(adapter, proposed, lookup, parsed)
        promos = assemble(proposed, verdicts, lookup, parsed)
        cross = [p for p in promos if p.get("coherent") and p.get("within_60s")]
        print(f"      {len(cross)} coherent cross-episode promo(s) kept")
    else:
        print("[2/6] stitch skipped")

    print("[3/6] rank + merge + waves")
    singles = rank(scored, per_episode)          # dedupe per episode, assign wave
    for c in cross:
        c["wave"] = _assign_wave(c)
    allp = singles + cross
    allp.sort(key=lambda p: (p["wave"], -p["composite"]))   # Wave 1 first, then composite
    for i, p in enumerate(allp, 1):
        p["rank"] = i

    print("[4/6] render script spans")
    for p in allp:
        if p.get("segments") and len(p["segments"]) > 1:
            continue                              # cross-ep span already built by stitch
        ep = parsed.get(p["source_file"])
        p["script_span"] = render_span(ep, p["start_sec"], p["end_sec"]) if ep else ""
        p["timecode"] = f"{_ts(p['start_sec'])}-{_ts(p['end_sec'])}"

    if do_audit:
        top = allp[:25]
        print(f"[5/6] self-audit (top {len(top)}) with {audit_model}")
        notes = audit(top, ModelAdapter(provider=provider, model=audit_model,
                                        api_key=api_key, base_url=base_url))
        for p in allp:
            a = notes.get(p["rank"])
            if a:
                p["flags"], p["audit_note"] = a["flags"], a["note"]
            else:
                p.setdefault("flags", [])
    else:
        for p in allp:
            p.setdefault("flags", [])
        print("[5/6] audit skipped")

    print("[6/6] hook-grounding check")
    for p in allp:
        v = hook_in_span(p.get("hook_line", ""), p.get("script_span", ""))
        if v is not None:
            p["hook_in_span"] = v
    return allp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("directory")
    ap.add_argument("--out", default="raw_outputs/promo_bundle.json")
    ap.add_argument("--provider", default="claude")
    ap.add_argument("--model", default=None)
    ap.add_argument("--audit-model", default="claude-opus-5-5")
    ap.add_argument("--per-episode", type=int, default=2)
    ap.add_argument("--max", type=int, default=12)
    ap.add_argument("--pairs", type=int, default=6)
    ap.add_argument("--no-stitch", action="store_true")
    ap.add_argument("--no-audit", action="store_true")
    args = ap.parse_args()

    t0 = time.time()
    bundle = run(args.directory, provider=args.provider, model=args.model,
                 audit_model=args.audit_model, per_episode=args.per_episode,
                 max_candidates=args.max, pairs=args.pairs,
                 do_stitch=not args.no_stitch, do_audit=not args.no_audit)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    json.dump(bundle, open(args.out, "w"), ensure_ascii=False, indent=2)
    ce = sum(1 for p in bundle if p.get("segments") and len(p["segments"]) > 1)
    fl = sum(1 for p in bundle if p.get("flags"))
    hk = sum(1 for p in bundle if p.get("hook_in_span") is False)
    print(f"\nwrote {len(bundle)} promos -> {args.out}  "
          f"({ce} cross-episode, {fl} self-audit flags, {hk} hook-grounding flags) "
          f"in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
