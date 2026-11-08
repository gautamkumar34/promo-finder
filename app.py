"""Promo Finder — Streamlit UI.

Default: shows a pre-computed run instantly (no API key needed, no screenplays
shipped). Optional: run live on a local folder with a provider of your choice.

    streamlit run app.py
"""
import json
import os
import streamlit as st

st.set_page_config(page_title="Promo Finder", page_icon="🎬", layout="wide")

BUNDLE = "raw_outputs/promo_bundle.json"          # real run on the Kuku pack (git-ignored, private)
DEMO_BUNDLE = "sample_screenplay/demo_bundle.json"  # synthetic non-Kuku demo (shipped publicly)
PROVIDERS = {
    "Claude Sonnet 5.5": ("claude", "claude-sonnet-5-5"),
    "Claude Opus 5.5": ("claude", "claude-opus-5-5"),
    "Gemini 3.8 Flash": ("gemini", "gemini-3.8-flash"),
}


@st.cache_data
def load_bundle(path):
    if os.path.exists(path):
        return json.load(open(path))
    return []


def score_bar(label, val):
    st.caption(f"{label} {val:.0f}/10")
    st.progress(min(max(val / 10, 0), 1.0))


def promo_card(p):
    with st.container(border=True):
        c1, c2 = st.columns([3, 1])
        with c1:
            wave = "🟢 Wave 1 · cold-audience hook" if p["wave"] == 1 \
                else "🟠 Wave 2 · high-drama retargeting"
            flag = "  ·  ⚠️ needs context" if p.get("needs_context") else ""
            st.markdown(f"**#{p['rank']} · Episode {p['episode_number']} · "
                        f"`{p.get('timecode','')}` ({p['duration_sec']:.0f}s)**{flag}")
            st.caption(wave)
            st.markdown(f"**🪝 Hook:** {p['hook_line']}")
            st.markdown(f"**✂️ Cliffhanger:** {p['cliffhanger_line']}")
            st.markdown(f"_{p['why']}_")
            if p.get("segments") and len(p["segments"]) > 1:
                st.caption(f"↔ cross-episode promo · {len(p['segments'])} segments")
            if p.get("flags"):
                st.warning("Self-audit: " + ", ".join(p["flags"]))
            if p.get("script_span"):
                with st.expander("📜 Script span (the clip)"):
                    st.code(p["script_span"], language=None)
        with c2:
            st.metric("Composite", f"{p['composite']:.1f}")
            score_bar("Hook", p["hook"])
            score_bar("Cliffhanger", p["cliffhanger"])
            score_bar("Standalone", p["standalone"])


# ---- sidebar -------------------------------------------------------------
st.sidebar.title("🎬 Promo Finder")
st.sidebar.caption("Finds the best 20–60s promo clips in a microdrama screenplay — "
                   "with exact cut points, hook, cliffhanger and posting order.")

provider_label = st.sidebar.selectbox("Model / provider", list(PROVIDERS), index=0,
                                       help="The LLM sits behind one adapter — swap in one click.")
provider, model = PROVIDERS[provider_label]

st.sidebar.divider()
wave_f = st.sidebar.radio("Posting wave", ["All", "Wave 1 only", "Wave 2 only"])
min_comp = st.sidebar.slider("Min composite score", 0.0, 10.0, 0.0, 0.5)
hide_ctx = st.sidebar.checkbox("Hide 'needs context' promos", value=False)

# ---- live run — swap the model ------------------------------------------
with st.sidebar.expander("⚙️ Run live — upload & swap the model"):
    st.caption("Runs the real pipeline with the provider chosen above. "
               "Upload a screenplay (or point at a local folder) and try a different "
               "model to see the one-line swap.")
    uploads = st.file_uploader("Upload screenplay .txt file(s)", type=["txt"],
                               accept_multiple_files=True,
                               help="Drop one or more screenplay .txt files in the same "
                                    "format as the demo show. On the deployed web app, "
                                    "use this — there is no server folder to point at.")
    live_dir = st.text_input("…or a local folder path", value="",
                             help="Only when running locally — a folder of .txt screenplays "
                                  "on your machine (e.g. `sample_screenplay`). Leave blank on "
                                  "the web and use the uploader above.")
    api_key = st.text_input("API key (optional)", type="password",
                            help="Used only for this run, held in memory — never stored, "
                                 "logged, or committed. Leave blank to use the server's key.")
    base_url = st.text_input("Base URL (optional)",
                             help="For an OpenAI-compatible / self-hosted endpoint. "
                                  "Leave blank for Anthropic or Google.")
    run = st.button("Find promos")
    if st.session_state.get("live_data"):
        if st.button("↩︎ Back to pre-computed results"):
            st.session_state.pop("live_data", None)
            st.session_state.pop("live_model", None)
            st.rerun()

data = None
if run:
    import glob
    import tempfile
    # source: uploaded files take precedence; else a local folder path
    src_dir = None
    if uploads:
        src_dir = tempfile.mkdtemp(prefix="promo_live_")
        for uf in uploads:
            with open(os.path.join(src_dir, os.path.basename(uf.name)), "wb") as w:
                w.write(uf.getbuffer())
    elif live_dir and os.path.isdir(live_dir):
        src_dir = live_dir
    elif live_dir:
        st.sidebar.error("Folder not found.")
    else:
        st.sidebar.warning("Upload a .txt screenplay, or give a local folder path.")

    if src_dir:
        from src.parse import parse_file
        from src.candidates import generate_candidates
        from src.score import score_episode
        from src.rank import rank
        from src.bundle import render_span
        from src.adapter import ModelAdapter
        files = sorted(glob.glob(os.path.join(src_dir, "*.txt")))
        if not files:
            st.sidebar.error("No .txt screenplays found.")
        else:
            try:
                adapter = ModelAdapter(provider=provider, model=model,
                                       api_key=api_key or None, base_url=base_url or None)
                scored = []
                prog = st.sidebar.progress(0.0, text="Scoring…")
                for i, f in enumerate(files, 1):
                    ep = parse_file(f)
                    scored.extend(score_episode(adapter, ep, generate_candidates(ep, 12)))
                    prog.progress(i / len(files), text=f"Scoring {i}/{len(files)}")
                promos = rank(scored, 2)
                cache = {}
                for p in promos:
                    if p["source_file"] not in cache:
                        cache[p["source_file"]] = parse_file(
                            os.path.join(src_dir, p["source_file"]))
                    ep = cache[p["source_file"]]
                    p["timecode"] = f"{int(p['start_sec']//60)}:{p['start_sec']%60:05.2f}-" \
                                    f"{int(p['end_sec']//60)}:{p['end_sec']%60:05.2f}"
                    p["script_span"] = render_span(ep, p["start_sec"], p["end_sec"])
                data = promos
                # persist so filters/dropdowns don't wipe the live run on the next rerun
                st.session_state["live_data"] = promos
                st.session_state["live_model"] = model
                st.sidebar.success(f"Scored {len(files)} episode(s) with {model} "
                                   "(live = scoring + ranking only; stitch & self-audit "
                                   "are in the full offline run).")
            except Exception as e:
                st.sidebar.error(f"Live run failed: {type(e).__name__}: {e}\n\n"
                                 "Check the provider/model and that a valid API key is set "
                                 "(field above, or server env).")

# ---- main ----------------------------------------------------------------
is_demo = False
if data is not None:
    # a live run just completed this cycle
    source_note = f"live run · {model}"
elif st.session_state.get("live_data"):
    # a live run from an earlier interaction — keep showing it through filter clicks
    data = st.session_state["live_data"]
    source_note = f"live run · {st.session_state.get('live_model', '')}"
else:
    data = load_bundle(BUNDLE)
    if data:
        source_note = "pre-computed run · Kuku input pack"
    else:
        data = load_bundle(DEMO_BUNDLE)
        is_demo = True
        source_note = "synthetic demo show · \"Inherit the Night\""

st.title("Ranked Promos")
if is_demo:
    st.info("📄 **Demo mode — synthetic screenplay.** The Kuku input pack is confidential, "
            "so this public demo runs on a 3-episode fictional show I wrote (\"Inherit the Night\"). "
            "The real run on all 50 Kuku episodes is in the raw-outputs Drive folder. "
            "Point the app at the private bundle, or use **Run live (local)**, to see the full run.")
if not data:
    st.info("No bundle found. Use **Run live (local)** in the sidebar, or generate "
            "`sample_screenplay/demo_bundle.json` / `raw_outputs/promo_bundle.json`.")
    st.stop()

# filters
view = [p for p in data
        if p["composite"] >= min_comp
        and not (hide_ctx and p.get("needs_context"))
        and (wave_f == "All"
             or (wave_f == "Wave 1 only" and p["wave"] == 1)
             or (wave_f == "Wave 2 only" and p["wave"] == 2))]

w1 = sum(1 for p in data if p["wave"] == 1)
a, b, c = st.columns(3)
a.metric("Promos", len(data))
b.metric("Wave 1 (post first)", w1)
c.metric("Showing", len(view))
st.caption(f"Source: {source_note}. Timecodes map 1:1 onto the episode video — "
           "an editor or an ffmpeg step cuts these spans. The script span is the clip.")
st.divider()

for p in view:
    promo_card(p)
