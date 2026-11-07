"""Build a self-contained UI bundle: each ranked promo + its rendered script
span, so the Streamlit app can display promos WITHOUT the raw screenplays
(keeps Kuku content out of any deployed/public app — confidentiality).

Usage:
    python -m src.bundle "<screenplays_dir>" [--ranked raw_outputs/ranked.json]
                         [--out raw_outputs/promo_bundle.json]
"""
from __future__ import annotations

import argparse
import glob
import json
import os

from .parse import parse_file


def _ts(x):
    return f"{int(x // 60)}:{x % 60:05.2f}"


def render_span(ep, start: float, end: float) -> str:
    """The promo clip as a mini-screenplay (the video stand-in)."""
    out = []
    for s in ep.scenes:
        beats = [b for b in s.beats
                 if b.start_sec is not None and b.start_sec < end and b.end_sec > start]
        if not beats:
            continue
        out.append(f"[{s.heading}]")
        for b in beats:
            tag = b.speaker or b.kind
            emo = f" ({b.emotion})" if b.emotion else ""
            out.append(f"  {_ts(b.start_sec)}  {tag}{emo}: {b.text}")
    return "\n".join(out)


def build(directory: str, ranked_path: str) -> list:
    promos = json.load(open(ranked_path))
    # cache parsed episodes by source_file
    cache = {}
    files = {os.path.basename(p): p for p in glob.glob(os.path.join(directory, "*.txt"))}
    out = []
    for p in promos:
        sf = p["source_file"]
        if sf not in cache and sf in files:
            cache[sf] = parse_file(files[sf])
        ep = cache.get(sf)
        span = render_span(ep, p["start_sec"], p["end_sec"]) if ep else ""
        q = dict(p)
        q["timecode"] = f"{_ts(p['start_sec'])}-{_ts(p['end_sec'])}"
        q["script_span"] = span
        out.append(q)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("directory")
    ap.add_argument("--ranked", default="raw_outputs/ranked.json")
    ap.add_argument("--out", default="raw_outputs/promo_bundle.json")
    args = ap.parse_args()
    bundle = build(args.directory, args.ranked)
    json.dump(bundle, open(args.out, "w"), ensure_ascii=False, indent=2)
    have_span = sum(1 for b in bundle if b["script_span"])
    print(f"wrote {len(bundle)} promos ({have_span} with script spans) -> {args.out}")


if __name__ == "__main__":
    main()
