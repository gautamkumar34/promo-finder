"""Stage 1 — Candidate promo windows (pure Python, $0, deterministic).

Anchor-end-first: a promo is defined by its cliffhanger END, so we anchor on
beat END-points and grow backward into 20-60s windows snapped to beat
boundaries. We do NOT judge hook quality here (that's the LLM's job in Stage 2);
we only enforce objective constraints and make sure good moments are covered.

End anchors (strongest first):
    episode_end   - microdramas are built to end on a hook
    sound_fx      - a cliffhanger sound cue
    cut_to_black  - an explicit hard cut
    scene_cut     - a scene boundary
    dialogue_end  - the end of a spoken line (a line can be the cliffhanger;
                    this is what lets us catch mid-scene reveals like the
                    Ep1 "Because he is marrying me." button)

Each candidate carries a window_id. Stages 2-4 reference windows by id;
timestamps are never authored by the LLM.

Usage:
    python -m src.candidates "<screenplays_dir>" [--max N] [--out candidates.json]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
from dataclasses import dataclass, asdict
from typing import Optional

from .parse import parse_file, Episode

DURATIONS = (22, 38, 55)          # short / medium / long, all inside 20-60s
MIN_DUR, MAX_DUR = 20.0, 60.0
DEFAULT_MAX = 12                  # candidates per episode (relaxed: batch scoring sends them cheap)
MERGE_GAP = 2.0                   # collapse anchor end-times within this many seconds

_ANCHOR_STRENGTH = {
    "episode_end": 4,
    "sound_fx": 3,
    "cut_to_black": 3,
    "scene_cut": 2,
    "dialogue_end": 1,
}


@dataclass
class Candidate:
    window_id: str
    episode_number: Optional[int]
    source_file: str
    start_sec: float
    end_sec: float
    duration_sec: float
    end_anchor: str
    anchor_strength: int
    beat_ids: list
    n_beats: int
    n_dialogue: int
    first_line: str
    last_line: str


def _flat_beats(ep: Episode) -> list:
    """All beats across scenes, time-ordered, with valid timestamps."""
    beats = [b for s in ep.scenes for b in s.beats
             if b.start_sec is not None and b.end_sec is not None]
    beats.sort(key=lambda b: (b.start_sec, b.end_sec))
    return beats


def _end_anchors(ep: Episode, beats: list) -> list:
    """List of (end_sec, anchor_kind)."""
    anchors = []
    if ep.duration_sec:
        anchors.append((ep.duration_sec, "episode_end"))
    for s in ep.scenes:
        if s.end_sec is not None:
            anchors.append((s.end_sec, "scene_cut"))
    for b in beats:
        if b.kind == "SOUND_FX":
            anchors.append((b.end_sec, "sound_fx"))
        elif b.kind == "CAMERA" and "cut to black" in b.text.lower():
            anchors.append((b.end_sec, "cut_to_black"))
        elif b.kind == "DIALOGUE":
            anchors.append((b.end_sec, "dialogue_end"))
    return anchors


def _covered(beats: list, start: float, end: float) -> list:
    """Beats overlapping [start, end]."""
    return [b for b in beats if b.start_sec < end and b.end_sec > start]


def _preview_lines(covered: list):
    first = next((b.text for b in covered if b.kind == "DIALOGUE"), "")
    last = next((b.text for b in reversed(covered) if b.kind == "DIALOGUE"), "")
    if not first and covered:
        first = covered[0].text
    if not last and covered:
        last = covered[-1].text
    return first[:160], last[:160]


def _merge_anchors(anchors: list) -> list:
    """Collapse end-times within MERGE_GAP; keep the strongest anchor kind
    (and that anchor's end time as the cluster representative).
    anchors: list of (end_sec, kind). Returns sorted [(end_sec, kind)]."""
    clusters = []  # [rep_end, kind, strength]
    for end_sec, kind in sorted(anchors, key=lambda x: x[0]):
        strength = _ANCHOR_STRENGTH[kind]
        placed = False
        for cl in clusters:
            if abs(cl[0] - end_sec) <= MERGE_GAP:
                if strength > cl[2]:
                    cl[0], cl[1], cl[2] = end_sec, kind, strength
                placed = True
                break
        if not placed:
            clusters.append([end_sec, kind, strength])
    return sorted((cl[0], cl[1]) for cl in clusters)


def _best_start(beat_starts: list, end_sec: float, dur: int):
    """Single start nearest to (end-dur) that keeps duration in [20,60]."""
    target = end_sec - dur
    if target < 0:
        return None
    cands = []
    lower = max((s for s in beat_starts if s <= target), default=None)
    upper = min((s for s in beat_starts if s >= target), default=None)
    for s in (lower, upper):
        if s is None:
            continue
        d = end_sec - s
        if MIN_DUR <= d <= MAX_DUR:
            cands.append((abs(d - dur), s))
    if not cands:
        return None
    return min(cands)[1]  # start closest to intended duration


def generate_candidates(ep: Episode, max_candidates: int = DEFAULT_MAX) -> list:
    beats = _flat_beats(ep)
    if not beats:
        return []
    beat_starts = sorted({b.start_sec for b in beats})
    anchors = _merge_anchors(_end_anchors(ep, beats))

    raw = {}  # (start,end) -> anchor_kind  (one start per duration)
    for end_sec, kind in anchors:
        for dur in DURATIONS:
            start = _best_start(beat_starts, end_sec, dur)
            if start is None:
                continue
            k = (round(start, 2), round(end_sec, 2))
            if k not in raw or _ANCHOR_STRENGTH[kind] > _ANCHOR_STRENGTH[raw[k]]:
                raw[k] = kind

    cands = []
    for (start, end), kind in raw.items():
        cov = _covered(beats, start, end)
        first, last = _preview_lines(cov)
        cands.append(Candidate(
            window_id="",  # assigned after selection
            episode_number=ep.number, source_file=ep.source_file,
            start_sec=start, end_sec=end, duration_sec=round(end - start, 2),
            end_anchor=kind, anchor_strength=_ANCHOR_STRENGTH[kind],
            beat_ids=[b.beat_id for b in cov], n_beats=len(cov),
            n_dialogue=sum(1 for b in cov if b.kind == "DIALOGUE"),
            first_line=first, last_line=last,
        ))

    # --- selection: cap structural so the climax doesn't crowd out interior
    #     cliffhangers; reserve the rest for dialogue-anchored windows spread
    #     evenly across the episode timeline (covers openings / mid reveals) ---
    structural = sorted((c for c in cands if c.end_anchor != "dialogue_end"),
                        key=lambda c: (-c.anchor_strength, c.start_sec))
    dialogue = sorted((c for c in cands if c.end_anchor == "dialogue_end"),
                      key=lambda c: c.end_sec)

    struct_cap = max(3, max_candidates // 2)
    chosen = structural[:struct_cap]
    slots = max_candidates - len(chosen)
    if slots > 0 and dialogue:
        step = max(1, len(dialogue) // slots)
        chosen.extend(dialogue[::step][:slots])
    # if still short (few dialogue anchors), backfill from leftover structural
    if len(chosen) < max_candidates:
        for c in structural[struct_cap:]:
            if c not in chosen:
                chosen.append(c)
            if len(chosen) >= max_candidates:
                break

    chosen.sort(key=lambda c: (c.start_sec, c.end_sec))
    for i, c in enumerate(chosen, 1):
        c.window_id = f"ep{ep.number or 0:03d}_w{i:02d}"
    return chosen


def _files(directory: str):
    return sorted(glob.glob(os.path.join(directory, "*.txt")))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("directory")
    ap.add_argument("--max", type=int, default=DEFAULT_MAX)
    ap.add_argument("--out", help="write all candidates to this JSON file")
    args = ap.parse_args()

    files = _files(args.directory)
    if not files:
        raise SystemExit(f"No .txt files in {args.directory}")

    all_c = []
    per_ep = []
    anchors = {}
    for path in files:
        ep = parse_file(path)
        cs = generate_candidates(ep, args.max)
        per_ep.append(len(cs))
        for c in cs:
            anchors[c.end_anchor] = anchors.get(c.end_anchor, 0) + 1
            all_c.append(asdict(c))

    print(f"episodes          : {len(files)}")
    print(f"total candidates  : {len(all_c)}")
    print(f"candidates/episode: min {min(per_ep)}  avg {sum(per_ep)/len(per_ep):.1f}  max {max(per_ep)}")
    print(f"by end_anchor     : {dict(sorted(anchors.items()))}")
    durs = [c['duration_sec'] for c in all_c]
    print(f"duration range    : {min(durs):.1f}s - {max(durs):.1f}s")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(all_c, f, ensure_ascii=False, indent=2)
        print(f"wrote             : {args.out}")


if __name__ == "__main__":
    main()
