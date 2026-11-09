# Promo Finder: Solution Doc

**Name:** Gautam Kumar · **Roll no:** 230106026 · **Problem chosen:** Problem 1, Find the Promos

**Links:** Live app → https://promo-clip-finder.streamlit.app · Code → https://github.com/gautamkumar34/promo-finder · Video → https://drive.google.com/file/d/1EooAcY0lPtLQ3OJzOrjRp6ne8b0BRMKY/view · Raw outputs → in this Drive folder

## Why I picked Problem 1

I picked this partly because I have felt the pain myself, since I once spent far longer finding the one twenty second moment worth posting from some footage than I spent editing it. It is also the closest thing to Kuku's real weekly job, where an editor picks promo moments by hand from every new episode, and it comes with data a tool can use, because every scene, line, and action carries an exact timestamp that lets the output be precise cut points. I set the others aside, because Problem 2 is a grounding problem of a kind I have already built, and Problem 3 asks you to invent a problem when I would rather solve a real one.

## The idea the whole thing rests on

Each episode is only one or two minutes of video, and the screenplay that comes with it is a transcript lined up to the clock, where every line and action has a start and end time down to a hundredth of a second. So the tool never looks at a single frame of video. It reads the text, decides where the best promo is, and returns the episode with a start and an end, and those timestamps drop straight onto the real video so that a human or a one line ffmpeg step does the cutting. Skipping video processing is the whole scale story, because it is what makes the tool cost pennies per episode.

## How it works

Code does what is objective and the model does what is a matter of taste. There are six stages.

1. **Parse (code).** The screenplay text becomes structured JSON, from episode to scenes to timestamped beats.
2. **Candidate windows (code).** The tool builds windows of 20 to 60 seconds from objective signals alone, such as duration, beat boundaries, and ends that fall on scene cuts or sound effects, and it never filters for hooks by keyword.
3. **Score (LLM, swappable).** Each window is rated 1 to 10 on hook, cliffhanger, and standalone clarity, and it returns the hook line, the cliffhanger line, and one sentence on why it works. There is one call per episode, and sending the full episode as context is what lets the model judge whether a clip truly stands alone.
4. **Stitch across episodes (LLM).** Some promos join an early hook to a later payoff, so the model proposes a pair of at most two segments, and a second pass reads both spans to confirm they cut together under sixty seconds.
5. **Rank and posting order.** Clips are ranked by a composite score and split into Wave 1, the broad hooks I would post first to a cold audience, and Wave 2, the high drama I would keep for retargeting warmer viewers.
6. **Self audit (LLM).** A stronger model, Opus, rereads the top picks and flags the weak ones for a human to review.

The model sits behind one small adapter, so changing the model or provider is a single dropdown value. I ran the pipeline on Claude, using Sonnet 5.5 for bulk work and Opus 5.5 as the critic, then verified the swap to Gemini 3.8 Flash on a live run with the same adapter and JSON contract on a free tier. The app also takes any provider's key at runtime, held in memory and never stored, so a reviewer can connect Kuku's own API without touching the code. The model never writes a timestamp, because it refers to a window only by its ID while every timecode comes from code, which stops it inventing the plausible timecodes that language models tend to produce.

## What it costs, and how it scales

Grounded in the real pack of 75,071 words, which is about 3K tokens per episode:

| Model | Per episode | Per 50 episodes | Per week (assumed) |
|---|---|---|---|
| Sonnet 5.5 (**measured**) | **\~$0.034** | **\~$1.70** | \~$85 |
| Opus 5.5 (extrapolated) | \~$0.07 | \~$3.40 | \~$170 |

The weekly figure assumes about 2,500 episodes, roughly 50 shows of 50 episodes, because the brief says there are new shows every week but gives no number, so that row scales linearly. The Sonnet figure is measured on the real full run, where 600 windows across all 50 episodes cost about $1.70 in about 14 minutes, using 246K input and 117K output tokens, and the Opus row is that same run repriced. Either way it is pennies per episode against hours of manual watching, and the Batch API would roughly halve it again because the offline run is not sensitive to latency.

**If episodes were longer.** These numbers are tuned to Kuku's format of one or two minute microdramas, and the architecture itself does not care about length because it takes text in and returns cut points. Two knobs are sized for short episodes. One call per episode works because a whole episode fits cheaply in one prompt, but a thirty to forty minute episode would cost roughly fifteen to twenty times more, and the cap of about twelve candidates would miss moments in a longer runtime. The fix is a two stage scan, where a cheap model finds the three or four hottest regions first and detailed scoring runs only there, which keeps cost below linear.

## How I know it's good, and where it isn't

I ran two blind checks, playing the editor myself with the scores hidden both times.

The first asked whether the score can tell a good promo from a bad one. I took 12 clips, half top rated and half bottom rated, shuffled them, and marked each post or skip. I posted 4 of the 6 top rated clips and skipped 5 of the 6 bottom rated ones, which is 9 of 12. With one labeler who also built the tool I read this narrowly, as evidence that the score separates clear good from clear bad while its top tier precision is only 4 of 6, or 67 percent.

The second asked whether it can pick the single best clip. Across 8 episodes I asked it to choose the one I would post from its top 3, and it matched me only 2 of 8 times, which is chance. So the honest takeaway is that it is a strong shortlister and a weak final ranker, which is why it narrows each episode to about three clips and leaves the last call to a human.

The real failures come from the actual runs. It over values a slow scene where something is coming, as in Ep22, a dark bedchamber poisoning that scored high although the first three seconds will not stop a scroll, and the Opus critic flagged it too. It sometimes cites a hook line that is not actually inside the clip, which the Opus critic caught on Ep44, so I added a deterministic code check that verifies the quoted dialogue of each hook appears in its window. That check flags 6 of the 57 quoted hooks, and in five of them the in-point simply starts a beat too late and clips the hook off, which the app now shows on the card and which is fixed by snapping the start back. It also has false negatives, since Ep39 scored low at 3.25 but I would post it. And the self audit is only a cross check, because the Opus critic flagged 15 of the top 25 picks and 16 across all 103, yet both critic and scorer are language models, so the human labels above are the real evidence.

## Assumptions I made where the brief was silent

I assumed a promo is 20 to 60 seconds long, opens with a hook in the first three seconds, ends unresolved, and stands alone, and I capped cross episode promos at two segments. I treated the screenplay timestamps as the source of truth for cut points while leaving the final frame trim to a human. For confidentiality I kept the Kuku pack out of the public repo, so the public demo runs on a synthetic screenplay I wrote and the real 50 episode outputs ship only through the private Drive link.

## Tools I used, and one place AI got it wrong

I used Claude for planning and most of the code, Streamlit for the interface, and the Claude API for scoring. An early generated plan was confident that I should detect hooks with a regex, matching bracketed markers like SLAP and SHOUTS along with any line ending in a question or exclamation mark. I grepped all 50 files first and found no bracketed markers at all, and that question and exclamation marks match about 35 percent of all dialogue, so the rule was matching noise and would have discarded the best hook in the pack, a quiet line with no punctuation. That is why the candidate stage uses only objective constraints and leaves hook judgment to the model, and checking the suggestion against the data is the single thing that most shaped the design.
