# Promo Finder — Solution Doc

**Name:** Gautam Kumar · **Roll no:** 230106026 · **Problem chosen:** 1 — Find the Promos

**Links:** Live app → [STREAMLIT URL]  ·  Code → [GITHUB REPO URL]  ·  Video → [LOOM/YOUTUBE URL]  ·  Raw outputs → in this Drive folder

> Export this to PDF (≤2 pages) for submission. The form has a single Drive-link field, so this doc is where the repo/app/video links live — keep them clickable.

## Which problem and why

I chose **Problem 1**, partly because I've felt this exact pain myself. I'd been trying to cut a Reel from longer footage, and finding the one 20–30 second moment actually worth posting is slow, frustrating work — a tool that does that is something I personally wanted. It's also the problem closest to Kuku's real weekly job: an editor hand-picks promo moments from every episode of every new show. And it comes with machine-readable data — screenplays where every scene, line and action carries an exact timestamp — so a tool can output **precise cut points** an editor uses immediately, which is what the task asks for.

On the other two: Problem 2 is a retrieval-and-grounding problem close to RAG systems I've already built, so it wouldn't have stretched me; Problem 3 asks you to bring your own problem, but I'd rather take on one that was new to me than invent one. Problem 1 was new, concrete, and personal — so that's the one I wanted to solve.

## The key idea

Each episode is a 1–2 minute video; the screenplay is a **time-aligned transcript** of it. So the tool reads cheap text, decides where the best promos are, and emits `(episode, start, end)` cut points that map 1:1 onto the real video. No video processing is needed — an editor (or an `ffmpeg` step) cuts the given spans. This is what makes it scale to every show at near-zero cost.

## How it works

A hybrid pipeline, so the right work goes to the right place:

1. **Parser (code, $0):** screenplay `.txt` → structured JSON (scenes → timestamped beats).
2. **Candidate windows (code, $0):** generate 20–60s windows on **objective** rules only — duration, beat boundaries, ends biased toward scene-cuts / sound-FX cliffhanger cues. No keyword "hook" filter (see failures).
3. **LLM scoring (swappable provider):** each candidate is scored 1–10 on **hook** (first 3s), **cliffhanger**, and **standalone clarity**, returning strict JSON plus the hook line, cliffhanger line, and one line on why it works. Behind a provider-agnostic `ModelAdapter`: **Claude** (Sonnet 5.5 / Opus 5.5) runs the full pipeline, and **Gemini 3.8 Flash** (free tier) runs it through the same one-line swap — I verified the Claude→Gemini swap on a live run (same adapter, same JSON contract, different provider). The app also exposes a runtime field to paste any provider's key (and base URL) and run live — held in memory only, never stored — so Kuku, or a reviewer in the interview, can connect whatever API they provide without touching the code. A live model swap is shown in the video.
4. **Cross-episode stitching (LLM, ≤2 segments):** promos can join moments across episodes (e.g. an early humiliation hook + a later revenge beat); the model validates coherence and keeps it ≤60s.
5. **Rank + posting order:** ranked by composite, split into **Wave 1** (broad cold-audience hooks) and **Wave 2** (high-drama retargeting) — my answer to "which would you post first."

**Division of labour:** code owns what is objective (timing, boundaries); the model owns what is subjective (is this a hook / cliffhanger / self-contained). A human reviews only the top-ranked candidates.

## How it scales to every show, and what it costs

Grounded in the pack (75,071 words ≈ ~3K tokens/episode):

| Model | Per episode | 50-ep show | 2,500 eps/wk* |
|---|---|---|---|
| Sonnet 5.5 (**measured**) | **~$0.034** | **~$1.70** | ~$85/wk |
| Opus 5.5 (extrapolated) | ~$0.07 | ~$3.4 | ~$170/wk |

\*50 shows × 50 eps/wk is my **assumed** volume (the brief says "new shows every week" but gives no number) — scale it linearly. The Sonnet row is **measured** on the real full run: 600 windows across 50 episodes for **~$1.70 in ~14 minutes** (246K input / 117K output tokens); the Opus row is that run's token counts repriced. Pennies per episode against hours of manual watching, and halvable again with the Batch API. Because the model sits behind an adapter, Kuku can swap in a stronger API key in one line.

## How I know it's good — including where it fails

I ran two **blind** human checks (me as the editor proxy, scores hidden both times):

- **Does the score tell good promos from bad? (separation)** — 12 clips, half the tool's top-rated and half its bottom-rated, shuffled; I marked each post/skip. I posted **4/6** of the top-rated and skipped **5/6** of the bottom-rated — **9/12**. It's a small test (n=12, one labeler who also built the tool, extreme top vs extreme bottom), so read it as: the score separates clear good from clear bad, but top-tier precision is only **4/6 (67%)** — about a third of top-rated clips still aren't postable.
- **Can it pick the single best? (fine ordering)** — 8 episodes, pick the one I'd post from the tool's top 3. I matched its #1 only **2/8** (at chance), and my disagreements tracked no single score. Ordering *within* the top few is near-noise.
- **Takeaway:** the tool is a useful **shortlister** but a weak **final-ranker** — so it narrows to the top ~3 per episode and a human makes the final pick. That's the human-in-the-loop split in the design, now backed by data, not asserted.

**Where it picks badly (real cases from the runs):**
- *It over-values a slow "something's coming" cut.* Ep22 (poisoning bedchamber) and Ep23 (a door creaking open) both scored high but I'd skip them — the payoff is there, but the first 3s won't stop a scroll. The Opus self-audit **independently flagged Ep22 as `weak_hook`**; Ep23 it didn't flag, yet Ep23 sits at **#2 in the ranked list** — a concrete case of the ranking putting a clip *I* would skip near the top.
- *It sometimes returns an ungrounded quote.* The scorer occasionally gives a hook/cliffhanger line that paraphrases rather than quotes the clip (e.g. Ep44's hook line isn't verbatim in the span). **Known limitation, not yet fixed** — the fix is to validate the line appears in the window and snap the in-point to include the hook beat; I chose not to re-run the full scorer late and destabilise the cited results.
- *It has false negatives too.* Ep39 scored low (3.25) but I'd post it — the tool misses good moments, not only over-picks bad ones.
- *The self-audit is a cross-check, not proof.* An Opus critic flags **15 of the top 25** promos; since critic and scorer are both LLMs, the human labels above are the real check.

## Assumptions
Promo = 20–60s, hook in first ~3s, ends unresolved, stands alone. Cross-episode promos capped at 2 segments. Screenplay timestamps are the cut-point source of truth. The input pack is kept out of the public repo (confidentiality); the public demo runs on a synthetic screenplay I wrote.

## Tools used, and one place AI got it wrong
Claude for planning and code; Streamlit for the UI; Claude API for scoring. **One place AI got it wrong:** a generated plan proposed detecting hooks with a regex (`[SLAP]`, `[SHOUTS]`, `?`, `!`). Grepping the 50 files showed **no** such markers and `?`/`!` matching ~35% of all dialogue — the rule matched noise and would have thrown away the best hook in the pack. I caught it by checking against the data, which is why hook-judgment is left to the model, not regex.
