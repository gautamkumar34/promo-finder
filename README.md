# Promo Finder

Reads a microdrama screenplay and finds the best **20–60s promo clips** for TikTok / Instagram / YouTube — returning the **exact cut points** (episode + start/end timestamps of every segment), a **hook** line, a **cliffhanger** line, one line on **why it works**, and a **posting order**.

Built for the Kuku AI Generalist assignment, **Problem 1: Find the Promos**.

> **Live demo runs on a synthetic show** (`sample_screenplay/`) because the Kuku input pack is confidential. The real run on all 50 Kuku episodes is in the submission's private Drive folder.

## The idea

Each episode is a 1–2 min video; the screenplay is a **time-aligned transcript** — every scene, line and action carries an exact timestamp. So the tool reads cheap text, decides where the best promos are, and emits `(episode, start, end)` cut points that map 1:1 onto the real video. A human (or an `ffmpeg` step) cuts the spans — **no video processing**, so it costs pennies per episode and scales to every show.

## How it works

A hybrid pipeline — code owns what's objective, the model owns what's subjective:

1. **Parse** (`src/parse.py`, code) — screenplay `.txt` → structured scenes/beats with timestamps.
2. **Candidate windows** (`src/candidates.py`, code) — 20–60s windows on objective rules only (durations, beat boundaries, ends biased to scene-cuts / sound-FX cues). No keyword "hook" filter.
3. **Score** (`src/score.py`, LLM) — each window rated 1–10 on hook / cliffhanger / standalone, returning strict JSON + the hook line, cliffhanger line and why. One call per episode.
4. **Cross-episode stitch** (`src/stitch.py`, LLM) — joins an early hook + later payoff into one ≤60s, ≤2-segment promo; validates coherence.
5. **Rank + posting order** (`src/rank.py`) — split into **Wave 1** (broad cold-audience hooks, post first) and **Wave 2** (high-drama retargeting).
6. **Self-audit** (`src/audit.py`, LLM) — an independent stronger model (Opus) flags weak picks; a human reviews the top few.

The LLM sits behind a provider-agnostic adapter (`src/adapter.py`) — **swap the model in one line.**

## Quick start

```bash
pip install -r requirements.txt
streamlit run app.py
```

The app opens on a **pre-computed ranked list** (no API key needed). To run the pipeline live:

- Open **"⚙️ Run live — upload & swap the model"** in the sidebar.
- **Upload** one or more screenplay `.txt` files (same format as `sample_screenplay/`), or give a **local folder path**.
- Pick a **provider/model** at the top, optionally paste an **API key** (held in memory only — never stored), and hit **Find promos**.

> Live mode runs **scoring + ranking** only (fast). Cross-episode stitch and self-audit are in the full offline run (see the solution doc).

## Swapping the model / provider

`src/adapter.py` exposes one contract: `complete_json(prompt) -> parsed`. Change one dropdown value (or one argument) and the pipeline is unchanged. Tested:

- **Claude** — `claude-sonnet-5-5` (workhorse) / `claude-opus-5-5` (critic) — `anthropic` SDK
- **Gemini** — `gemini-3.8-flash` (free tier) — `google-genai` SDK — Claude→Gemini swap verified on a live run
- **OpenAI / OpenAI-compatible** — pass a key + base URL (stub; drop in the SDK call to enable)

```bash
export ANTHROPIC_API_KEY=...   # Claude
export GOOGLE_API_KEY=...        # Gemini (free tier)
```

## How good is it (honest)

Two blind human checks (scores hidden):

- **Separation** (does the score tell good from bad?): posted 4/6 of the tool's top-rated clips, skipped 5/6 of its bottom-rated — the score separates clear good from clear bad, but top-tier precision is ~67%.
- **Ordering** (can it pick *the* best of the top 3?): matched only 2/8 — fine ordering is near-noise.

**So it's a useful shortlister, not a precise ranker** — it narrows to the top ~3 per episode and a human makes the final pick. Failure cases (over-valuing slow "something's coming" cuts; occasional ungrounded hook quotes) are documented in the solution doc.

## Layout

```
promo-finder/
  app.py                 # Streamlit UI (pre-computed view + live upload/swap)
  src/
    parse.py candidates.py adapter.py score.py stitch.py rank.py audit.py bundle.py
  sample_screenplay/     # synthetic demo show (no Kuku content) + demo_bundle.json
  requirements.txt
  .env.example
```

The Kuku input pack and the real `raw_outputs/` are **not** in this repo (confidentiality) — they're shared only via the private submission link.
