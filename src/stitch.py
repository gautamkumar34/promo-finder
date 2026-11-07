"""Stage 3 — Cross-episode stitch (bounded, 2 segments max).

A promo can join moments across episodes (brief: "from one episode or across
several"). We pair a strong opening HOOK window with a later PAYOFF window from
the same character arc into one <=60s, 2-segment promo.

Cheap + accurate, two steps (per the plan):
  1) propose pairs from a COMPACT INDEX (gists only — not the 150K-token pack)
  2) validate finalists by reading the two real script spans (catch context-bleed)

Segments use each episode's best SHORT window (<=30s) so A+B fits <=60s.

Usage:
    python -m src.stitch "<screenplays_dir>" [--scored raw_outputs/scored.json]
                         [--pairs 6] [--out raw_outputs/stitched.json]
"""
from __future__ import annotations

import argparse
import glob
import json
import os

from .parse import parse_file
from .bundle import render_span, _ts
from .adapter import ModelAdapter

MAX_SEG = 30.0      # per-segment cap so two segments stay <=60s
MAX_TOTAL = 60.0


def _speakers(ep, start, end):
    names = []
    for s in ep.scenes:
        for b in s.beats:
            if b.kind == "DIALOGUE" and b.speaker and b.start_sec is not None \
                    and b.start_sec < end and b.end_sec > start:
                if b.speaker not in names:
                    names.append(b.speaker)
    return names[:5]


def build_index(scored, parsed):
    """Best short window per episode -> compact index entry."""
    by_ep = {}
    for r in scored:
        by_ep.setdefault(r["episode_number"], []).append(r)
    index, lookup = [], {}
    for ep_num, windows in sorted(by_ep.items()):
        short = [w for w in windows if w["duration_sec"] <= MAX_SEG] or windows
        best = max(short, key=lambda w: w["composite"])
        ep = parsed.get(best["source_file"])
        chars = _speakers(ep, best["start_sec"], best["end_sec"]) if ep else []
        index.append({
            "window_id": best["window_id"], "episode": ep_num,
            "duration": best["duration_sec"],
            "hook": best["hook"], "cliffhanger": best["cliffhanger"],
            "standalone": best["standalone"],
            "characters": chars,
            "gist": f"{best['hook_line']} -> {best['cliffhanger_line']}",
        })
        lookup[best["window_id"]] = best
    return index, lookup


def _index_block(index):
    rows = []
    for e in index:
        rows.append(f"{e['window_id']} | Ep{e['episode']} | {e['duration']:.0f}s "
                    f"| h{e['hook']:.0f}/c{e['cliffhanger']:.0f}/s{e['standalone']:.0f} "
                    f"| chars: {', '.join(e['characters']) or '—'} | {e['gist']}")
    return "\n".join(rows)


PROPOSE_SYS = ("You build cross-episode promo pairs for a vertical microdrama. "
               "You join two moments into one short clip that pulls a stranger in.")


def propose_pairs(adapter, index, n_pairs):
    prompt = f"""Below is the best promo window from each episode of ONE show, in
episode order. Propose up to {n_pairs} CROSS-EPISODE promos. Each joins TWO
window_ids into a single clip:
  segment A = an earlier strong HOOK (grabs a stranger)
  segment B = a LATER payoff that raises the stakes for the SAME character/arc
Rules: A's episode < B's episode; they must share a character or clear arc; the
join must make sense to a new viewer. Prefer high hook on A, high cliffhanger on B.

Return ONLY JSON: [{{"seg_a":"<window_id>","seg_b":"<window_id>","arc":"<character/arc>","why":"<one line>"}}]

=== BEST WINDOW PER EPISODE ===
{_index_block(index)}
"""
    out = adapter.complete_json(prompt, system=PROPOSE_SYS)
    if isinstance(out, dict):
        out = out.get("pairs") or out.get("promos") or [out]
    return [p for p in out if isinstance(p, dict) and p.get("seg_a") and p.get("seg_b")]


VALIDATE_SYS = ("You are a skeptical promo editor. You reject cross-episode cuts "
                "that a new viewer couldn't follow.")


def validate_pairs(adapter, pairs, lookup, parsed):
    blocks = []
    for i, p in enumerate(pairs):
        a, b = lookup.get(p["seg_a"]), lookup.get(p["seg_b"])
        if not a or not b:
            continue
        ea, eb = parsed.get(a["source_file"]), parsed.get(b["source_file"])
        span_a = render_span(ea, a["start_sec"], a["end_sec"]) if ea else ""
        span_b = render_span(eb, b["start_sec"], b["end_sec"]) if eb else ""
        blocks.append(f"PAIR {i}: {p['seg_a']} + {p['seg_b']} (arc: {p.get('arc','')})\n"
                      f"-- SEGMENT A (Ep{a['episode_number']}) --\n{span_a}\n"
                      f"-- SEGMENT B (Ep{b['episode_number']}) --\n{span_b}\n")
    prompt = f"""Judge each proposed 2-part promo as a stranger. For each PAIR index,
return: coherent (does B follow A understandably?), context_bleed (true if a new
viewer would be lost), and a one-line verdict.

Return ONLY JSON: [{{"pair":0,"coherent":true,"context_bleed":false,"verdict":"..."}}]

{chr(10).join(blocks)}"""
    out = adapter.complete_json(prompt, system=VALIDATE_SYS)
    if isinstance(out, dict):
        out = out.get("results") or [out]
    return {int(r["pair"]): r for r in out if isinstance(r, dict) and "pair" in r}


def assemble(pairs, verdicts, lookup, parsed):
    promos = []
    for i, p in enumerate(pairs):
        a, b = lookup.get(p["seg_a"]), lookup.get(p["seg_b"])
        if not a or not b:
            continue
        v = verdicts.get(i, {})
        total = a["duration_sec"] + b["duration_sec"]
        ea, eb = parsed.get(a["source_file"]), parsed.get(b["source_file"])
        span = (f"[SEGMENT A — Ep{a['episode_number']} {_ts(a['start_sec'])}-{_ts(a['end_sec'])}]\n"
                + (render_span(ea, a["start_sec"], a["end_sec"]) if ea else "")
                + f"\n\n[SEGMENT B — Ep{b['episode_number']} {_ts(b['start_sec'])}-{_ts(b['end_sec'])}]\n"
                + (render_span(eb, b["start_sec"], b["end_sec"]) if eb else ""))
        flags = []
        if v.get("context_bleed"):
            flags.append("context_bleed")
        promos.append({
            "kind": "cross_episode",
            "segments": [
                {"episode": a["episode_number"], "window_id": a["window_id"],
                 "start_sec": a["start_sec"], "end_sec": a["end_sec"]},
                {"episode": b["episode_number"], "window_id": b["window_id"],
                 "start_sec": b["start_sec"], "end_sec": b["end_sec"]},
            ],
            "arc": p.get("arc", ""),
            "episode_number": f"{a['episode_number']}+{b['episode_number']}",
            "duration_sec": round(total, 1),
            "within_60s": total <= MAX_TOTAL,
            "coherent": bool(v.get("coherent", False)),
            "hook": a["hook"], "cliffhanger": b["cliffhanger"],
            "standalone": min(a["standalone"], b["standalone"]),
            "composite": round((a["hook"] * 0.4 + b["cliffhanger"] * 0.4
                                + min(a["standalone"], b["standalone"]) * 0.2), 2),
            "hook_line": a["hook_line"],
            "cliffhanger_line": b["cliffhanger_line"],
            "why": p.get("why", "") + (f" — {v.get('verdict','')}" if v.get("verdict") else ""),
            "needs_context": bool(v.get("context_bleed")),
            "flags": flags,
            "timecode": f"Ep{a['episode_number']} + Ep{b['episode_number']}",
            "script_span": span,
        })
    return promos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("directory")
    ap.add_argument("--scored", default="raw_outputs/scored.json")
    ap.add_argument("--pairs", type=int, default=6)
    ap.add_argument("--provider", default="claude")
    ap.add_argument("--model", default=None)
    ap.add_argument("--out", default="raw_outputs/stitched.json")
    args = ap.parse_args()

    scored = json.load(open(args.scored))
    files = {os.path.basename(p): p for p in glob.glob(os.path.join(args.directory, "*.txt"))}
    parsed = {name: parse_file(path) for name, path in files.items()}

    adapter = ModelAdapter(provider=args.provider, model=args.model)
    index, lookup = build_index(scored, parsed)
    print(f"index: {len(index)} episode-best windows")
    pairs = propose_pairs(adapter, index, args.pairs)
    print(f"proposed {len(pairs)} cross-episode pairs")
    verdicts = validate_pairs(adapter, pairs, lookup, parsed)
    promos = assemble(pairs, verdicts, lookup, parsed)
    kept = [p for p in promos if p["coherent"] and p["within_60s"]]

    json.dump(promos, open(args.out, "w"), ensure_ascii=False, indent=2)
    print(f"assembled {len(promos)} ({len(kept)} coherent & <=60s) -> {args.out}\n")
    for p in promos:
        ok = "✓" if (p["coherent"] and p["within_60s"]) else "✗"
        print(f"  {ok} {p['timecode']} ({p['duration_sec']:.0f}s) arc:{p['arc'][:28]}")
        print(f"     A hook : {p['hook_line'][:60]}")
        print(f"     B cliff: {p['cliffhanger_line'][:60]}")
        print(f"     {p['why'][:90]}")


if __name__ == "__main__":
    main()
