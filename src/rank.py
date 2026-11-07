"""Stage 4 — Rank the scored windows into a final, postable promo list.

- de-overlap: within an episode, keep only the best non-overlapping windows
  (so we don't ship five near-identical clips of the same moment)
- rank globally by composite
- posting order: Wave 1 (broad cold-audience hooks — stand alone AND hook hard)
  posted first, then Wave 2 (high-drama retargeting — cliffhanger-driven, may
  lean on a little context)

Usage:
    python -m src.rank [--scored raw_outputs/scored.json]
                       [--per-episode 2] [--out raw_outputs/ranked.json]
"""
from __future__ import annotations

import argparse
import json

# Wave 1 thresholds — works for a stranger with no context
W1_HOOK, W1_STAND = 7.0, 7.0


def _overlap(a, b) -> bool:
    return a["start_sec"] < b["end_sec"] and b["start_sec"] < a["end_sec"]


def _assign_wave(r: dict) -> int:
    if r["hook"] >= W1_HOOK and r["standalone"] >= W1_STAND and not r["needs_context"]:
        return 1
    return 2


def dedupe_episode(windows: list, keep: int) -> list:
    """Greedy: highest composite first, skip windows overlapping an already-kept one."""
    chosen = []
    for w in sorted(windows, key=lambda x: -x["composite"]):
        if any(_overlap(w, c) for c in chosen):
            continue
        chosen.append(w)
        if len(chosen) >= keep:
            break
    return chosen


def rank(scored: list, per_episode: int = 2) -> list:
    by_ep = {}
    for r in scored:
        by_ep.setdefault(r["episode_number"], []).append(r)

    promos = []
    for ep, windows in by_ep.items():
        promos.extend(dedupe_episode(windows, per_episode))

    for p in promos:
        p["wave"] = _assign_wave(p)

    # Wave 1 first, then by composite within each wave
    promos.sort(key=lambda p: (p["wave"], -p["composite"]))
    for i, p in enumerate(promos, 1):
        p["rank"] = i
    return promos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scored", default="raw_outputs/scored.json")
    ap.add_argument("--per-episode", type=int, default=2)
    ap.add_argument("--out", default="raw_outputs/ranked.json")
    args = ap.parse_args()

    scored = json.load(open(args.scored))
    promos = rank(scored, args.per_episode)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(promos, f, ensure_ascii=False, indent=2)

    w1 = sum(1 for p in promos if p["wave"] == 1)
    print(f"ranked {len(promos)} promos ({w1} Wave 1, {len(promos) - w1} Wave 2) -> {args.out}\n")
    print("TOP 10:")
    for p in promos[:10]:
        print(f"  #{p['rank']:2} W{p['wave']} {p['composite']:4.1f}  Ep{p['episode_number']:>2} "
              f"[{p['start_sec']:.0f}-{p['end_sec']:.0f}s] "
              f"h{p['hook']:.0f}/c{p['cliffhanger']:.0f}/s{p['standalone']:.0f}")
        print(f"       hook : {p['hook_line'][:66]}")
        print(f"       cliff: {p['cliffhanger_line'][:66]}")


if __name__ == "__main__":
    main()
