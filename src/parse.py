"""Stage 0 — Parser: microdrama screenplay .txt -> structured JSON.

Deterministic, no external dependencies. Turns one screenplay file into:

    Episode { number, logline, continuity_notes,
              scenes: [ Scene { index, heading, start_sec, end_sec,
                                beats: [ Beat {...} ] } ] }

Beat = { kind, speaker, emotion, text, start_sec, end_sec, beat_id }
  kind in {CAMERA, ACTION, SOUND_FX, DIALOGUE}

Usage:
    python -m src.parse "<screenplays_dir>" --out parsed/     # dump one JSON per episode
    python -m src.parse "<screenplays_dir>"                   # just print stats
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
from dataclasses import dataclass, field, asdict
from typing import Optional

# ---- regex ---------------------------------------------------------------
_TIME = re.compile(r"(\d+):(\d{2}(?:\.\d+)?)")
_HEADER = re.compile(r"^\*\*(.+?):\*\*\s*$")          # **CAMERA:** / **NAME (emotion):**
_STARTEND = re.compile(r"Start:\s*\(([^)]+)\)\s*\|\s*End:\s*\(([^)]+)\)")
_SCENE = re.compile(r"^SCENE\s+(\d+)", re.IGNORECASE)

_FIXED_KINDS = {"CAMERA": "CAMERA", "ACTION": "ACTION", "SOUND FX": "SOUND_FX"}


def to_sec(ts: str) -> Optional[float]:
    """'02:18.00' -> 138.0 seconds."""
    m = _TIME.search(ts or "")
    if not m:
        return None
    return round(int(m.group(1)) * 60 + float(m.group(2)), 2)


# ---- data model ----------------------------------------------------------
@dataclass
class Beat:
    beat_id: str
    kind: str
    speaker: Optional[str]
    emotion: Optional[str]
    text: str
    start_sec: Optional[float]
    end_sec: Optional[float]


@dataclass
class Scene:
    index: int
    heading: str
    start_sec: Optional[float]
    end_sec: Optional[float]
    beats: list = field(default_factory=list)


@dataclass
class Episode:
    number: Optional[int]
    title: str
    logline: str
    continuity_notes: str
    source_file: str
    duration_sec: Optional[float]
    scenes: list = field(default_factory=list)


# ---- header parsing ------------------------------------------------------
def _parse_header(inner: str):
    """'MATRIARCH (O.S.) (Cold)' -> (kind, speaker, emotion)."""
    paren = inner.find("(")
    if paren == -1:
        name, emotion = inner.strip(), None
    else:
        name = inner[:paren].strip()
        emotion = inner[paren:].strip() or None
    kind = _FIXED_KINDS.get(name.upper())
    if kind:
        return kind, None, emotion
    return "DIALOGUE", name, emotion


# ---- main parse ----------------------------------------------------------
def parse_text(text: str, source_file: str = "") -> Episode:
    lines = text.splitlines()
    ep = Episode(number=None, title="", logline="", continuity_notes="",
                 source_file=source_file, duration_sec=None)

    i, n = 0, len(lines)

    # --- preamble (before "--- SCRIPT START ---") ---
    while i < n and "SCRIPT START" not in lines[i]:
        ln = lines[i].strip()
        if ln.upper().startswith("EPISODE NUMBER:"):
            ep.title = ln.split(":", 1)[1].strip()
            num = re.search(r"(\d+)", ep.title)
            ep.number = int(num.group(1)) if num else None
        elif ln.upper().startswith("EPISODE LOGLINE:"):
            ep.logline = ln.split(":", 1)[1].strip()
        elif ln.upper().startswith("CONTINUITY NOTES:"):
            ep.continuity_notes = ln.split(":", 1)[1].strip()
        i += 1

    cur: Optional[Scene] = None
    beat_seq = 0

    while i < n:
        raw = lines[i]
        ln = raw.strip()

        if "SCRIPT END" in ln:
            break

        m_scene = _SCENE.match(ln)
        if m_scene:
            cur = Scene(index=int(m_scene.group(1)), heading="",
                        start_sec=None, end_sec=None)
            ep.scenes.append(cur)
            i += 1
            continue

        if cur is not None and ln.lower().startswith("scene heading:"):
            cur.heading = ln.split(":", 1)[1].strip()
            i += 1
            continue
        if cur is not None and ln.lower().startswith("scene start:"):
            cur.start_sec = to_sec(ln.split(":", 1)[1])
            i += 1
            continue
        if cur is not None and ln.lower().startswith("scene end:"):
            cur.end_sec = to_sec(ln.split(":", 1)[1])
            i += 1
            continue

        m_head = _HEADER.match(ln)
        if m_head:
            kind, speaker, emotion = _parse_header(m_head.group(1))
            start_sec = end_sec = None
            j = i + 1
            # next non-empty line should carry Start/End
            while j < n and not lines[j].strip():
                j += 1
            if j < n:
                m_se = _STARTEND.search(lines[j])
                if m_se:
                    start_sec = to_sec(m_se.group(1))
                    end_sec = to_sec(m_se.group(2))
                    j += 1
            # collect text until blank line OR next header OR scene/boundary
            body = []
            while j < n:
                t = lines[j].strip()
                if (not t) or _HEADER.match(t) or _SCENE.match(t) \
                        or "SCRIPT END" in t:
                    break
                body.append(t)
                j += 1
            beat_seq += 1
            beat = Beat(
                beat_id=f"b{beat_seq:03d}",
                kind=kind, speaker=speaker, emotion=emotion,
                text=" ".join(body).strip(),
                start_sec=start_sec, end_sec=end_sec,
            )
            if cur is None:  # defensive: beat before any scene
                cur = Scene(index=0, heading="", start_sec=None, end_sec=None)
                ep.scenes.append(cur)
            cur.beats.append(beat)
            i = j
            continue

        i += 1

    # episode duration = last scene end (fallback: max beat end)
    ends = [s.end_sec for s in ep.scenes if s.end_sec is not None]
    if ends:
        ep.duration_sec = max(ends)
    else:
        be = [b.end_sec for s in ep.scenes for b in s.beats if b.end_sec is not None]
        ep.duration_sec = max(be) if be else None

    return ep


def parse_file(path: str) -> Episode:
    with open(path, "r", encoding="utf-8") as f:
        return parse_text(f.read(), source_file=os.path.basename(path))


def episode_to_dict(ep: Episode) -> dict:
    return asdict(ep)


# ---- CLI -----------------------------------------------------------------
def _episode_files(directory: str):
    return sorted(glob.glob(os.path.join(directory, "*.txt")))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("directory", help="folder of screenplay .txt files")
    ap.add_argument("--out", help="write one JSON per episode into this dir")
    args = ap.parse_args()

    files = _episode_files(args.directory)
    if not files:
        raise SystemExit(f"No .txt files in {args.directory}")

    if args.out:
        os.makedirs(args.out, exist_ok=True)

    tot_scenes = tot_beats = 0
    kinds = {}
    problems = []
    for path in files:
        ep = parse_file(path)
        nb = sum(len(s.beats) for s in ep.scenes)
        tot_scenes += len(ep.scenes)
        tot_beats += nb
        for s in ep.scenes:
            for b in s.beats:
                kinds[b.kind] = kinds.get(b.kind, 0) + 1
                if b.start_sec is None or b.end_sec is None:
                    problems.append(f"{ep.source_file}:{b.beat_id} missing timestamp")
        if not ep.scenes or nb == 0:
            problems.append(f"{ep.source_file}: no scenes/beats parsed")
        if args.out:
            stem = os.path.splitext(os.path.basename(path))[0]
            with open(os.path.join(args.out, stem + ".json"), "w", encoding="utf-8") as f:
                json.dump(episode_to_dict(ep), f, ensure_ascii=False, indent=2)

    print(f"episodes parsed : {len(files)}")
    print(f"total scenes    : {tot_scenes}")
    print(f"total beats     : {tot_beats}")
    print(f"beats by kind   : {dict(sorted(kinds.items()))}")
    print(f"problems        : {len(problems)}")
    for p in problems[:20]:
        print("  -", p)


if __name__ == "__main__":
    main()
