"""Stage 2 — LLM scoring, batched one call per episode.

Sends the full episode once + the numbered candidate windows; the model scores
each window_id on hook / cliffhanger / standalone and returns a JSON array.
The model never authors timestamps — it only references window_id.

Usage:
    python -m src.score "<screenplays_dir>" [--provider claude] [--model ...]
                        [--max 12] [--limit N] [--out raw_outputs/scored.json]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import time

from .parse import parse_file, Episode
from .candidates import generate_candidates
from .adapter import ModelAdapter

# composite weights — hook matters most for a scrolling stranger
W_HOOK, W_CLIFF, W_STAND = 0.40, 0.35, 0.25


def _ts(x):
    return f"{int(x // 60)}:{x % 60:05.2f}"


def render_transcript(ep: Episode) -> str:
    lines = []
    for s in ep.scenes:
        lines.append(f"\n[SCENE {s.index}] {_ts(s.start_sec or 0)}-{_ts(s.end_sec or 0)} {s.heading}")
        for b in s.beats:
            tag = b.speaker or b.kind
            emo = f" ({b.emotion})" if b.emotion else ""
            lines.append(f"[{_ts(b.start_sec)}-{_ts(b.end_sec)}] {tag}{emo}: {b.text}")
    return "\n".join(lines)


def _candidate_table(cands) -> str:
    rows = []
    for c in cands:
        rows.append(f"{c.window_id} | {_ts(c.start_sec)}-{_ts(c.end_sec)} "
                    f"| {c.duration_sec:.0f}s | ends_on:{c.end_anchor}")
    return "\n".join(rows)


SYSTEM = (
    "You are a promo editor for vertical microdramas (the 1-2 minute shows on "
    "TikTok, Reels and YouTube Shorts). You pick 20-60s clips from an episode "
    "that make a scrolling stranger stop and need the next part."
)


def build_prompt(ep: Episode, cands) -> str:
    return f"""EPISODE {ep.number}: {ep.title}
LOGLINE: {ep.logline}

Below is the full episode as a timestamped transcript, then a list of candidate
promo windows. Score EVERY window. Judge each clip as a stranger who has never
seen the show.

For each window_id give integer scores 1-10:
- hook        : do the FIRST ~3 seconds grab a scroller? (a slap, a reveal, a
                shocking line, a striking image). A slow setup scores low.
- cliffhanger : does the clip END unresolved, forcing "what happens next?"
- standalone  : understandable with ZERO prior context? Penalize clips that lean
                on unexplained backstory or too many named characters.
Also return:
- hook_line        : the exact line/action in the opening that hooks (short quote)
- cliffhanger_line : the ending beat it cuts on (short quote)
- why              : one short sentence on why it works (or doesn't)
- needs_context    : true if a new viewer would be confused without backstory

Return ONLY a JSON array, one object per window_id, no prose:
[{{"window_id":"...","hook":8,"cliffhanger":7,"standalone":9,"hook_line":"...","cliffhanger_line":"...","why":"...","needs_context":false}}]

=== TRANSCRIPT ===
{render_transcript(ep)}

=== CANDIDATE WINDOWS (score all {len(cands)}) ===
{_candidate_table(cands)}
"""


def score_episode(adapter: ModelAdapter, ep: Episode, cands) -> list:
    prompt = build_prompt(ep, cands)
    result = adapter.complete_json(prompt, system=SYSTEM)
    if isinstance(result, dict):  # tolerate {"windows":[...]} or single obj
        result = result.get("windows") or result.get("results") or [result]
    by_id = {r.get("window_id"): r for r in result if isinstance(r, dict)}

    scored = []
    for c in cands:
        r = by_id.get(c.window_id, {})
        h = float(r.get("hook", 0) or 0)
        cl = float(r.get("cliffhanger", 0) or 0)
        st = float(r.get("standalone", 0) or 0)
        composite = round(W_HOOK * h + W_CLIFF * cl + W_STAND * st, 2)
        d = {
            "window_id": c.window_id,
            "episode_number": c.episode_number,
            "source_file": c.source_file,
            "start_sec": c.start_sec, "end_sec": c.end_sec,
            "duration_sec": c.duration_sec, "end_anchor": c.end_anchor,
            "hook": h, "cliffhanger": cl, "standalone": st, "composite": composite,
            "hook_line": r.get("hook_line", ""),
            "cliffhanger_line": r.get("cliffhanger_line", ""),
            "why": r.get("why", ""),
            "needs_context": bool(r.get("needs_context", False)),
            "scored": bool(r),
        }
        scored.append(d)
    return scored


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("directory")
    ap.add_argument("--provider", default="claude")
    ap.add_argument("--model", default=None)
    ap.add_argument("--max", type=int, default=12)
    ap.add_argument("--limit", type=int, default=None, help="only first N episodes")
    ap.add_argument("--out", default="raw_outputs/scored.json")
    args = ap.parse_args()

    files = sorted(glob.glob(os.path.join(args.directory, "*.txt")))
    if args.limit:
        files = files[:args.limit]
    adapter = ModelAdapter(provider=args.provider, model=args.model)
    print(f"scoring {len(files)} episodes with {adapter}")

    all_scored, tin, tout = [], 0, 0
    t0 = time.time()
    for i, path in enumerate(files, 1):
        ep = parse_file(path)
        cands = generate_candidates(ep, args.max)
        try:
            scored = score_episode(adapter, ep, cands)
        except Exception as e:
            print(f"  [{i}/{len(files)}] Ep{ep.number}: ERROR {type(e).__name__}: {str(e)[:100]}")
            continue
        all_scored.extend(scored)
        u = getattr(adapter, "last_usage", {}) or {}
        tin += u.get("in") or 0
        tout += u.get("out") or 0
        top = max(scored, key=lambda s: s["composite"])
        print(f"  [{i}/{len(files)}] Ep{ep.number}: {len(scored)} scored | "
              f"top {top['composite']} {top['window_id']} "
              f"(h{top['hook']:.0f}/c{top['cliffhanger']:.0f}/s{top['standalone']:.0f})")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(all_scored, f, ensure_ascii=False, indent=2)

    dt = time.time() - t0
    # Sonnet 5.5 pricing: $2/1M in, $10/1M out
    cost = tin / 1e6 * 2 + tout / 1e6 * 10
    print(f"\nwrote {len(all_scored)} scored windows -> {args.out}")
    print(f"tokens: in {tin:,}  out {tout:,}  | ~${cost:.3f} (Sonnet 5.5 rate) | {dt:.0f}s")


if __name__ == "__main__":
    main()
