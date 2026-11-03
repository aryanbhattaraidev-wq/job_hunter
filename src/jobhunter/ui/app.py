"""Central intake + dashboard. Everything a user must provide is collected here, in order."""
import json, tempfile
from pathlib import Path
import streamlit as st
from jobhunter import config as C, db, pipeline, llm, resume_import as R
from jobhunter.profile import load_profile, save_profile, Profile, Bullet, Entry
from jobhunter.llm import DEFAULTS

C.load_dotenv()
st.set_page_config(page_title="Job Hunter", page_icon="🎯", layout="wide")
cfg = C.load_config()
prof = load_profile()

STEPS = ["1 · Resume", "2 · What you want", "3 · Sources", "4 · AI provider", "5 · Notifications", "6 · Jobs & CVs", "7 · Applications"]
done = [bool(prof), cfg.onboarded, True, llm.available(), cfg.notify.telegram_enabled or cfg.notify.email_enabled, True, True]
page = st.sidebar.radio("Setup", STEPS, format_func=lambda s: ("✅ " if done[STEPS.index(s)] else "⬜ ") + s)
st.sidebar.caption("Everything stays on your machine. Secrets go to a local .env file. Nothing is ever submitted without you.")


def secret_input(label, env, help_=""):
    import os
    cur = os.environ.get(env, "")
    v = st.text_input(label, value="", type="password", placeholder="•••• saved" if cur else "", help=help_)
    if v:
        C.set_env_secret(env, v)
        st.success(f"{env} saved")
    return bool(cur or v)


if page == STEPS[0]:
    st.header("Your resume")
    st.write("Upload any resume (PDF or text). It becomes your **master profile**: the only source of facts any tailored CV can use.")
    up = st.file_uploader("Resume", type=["pdf", "txt", "md"])
    if up and st.button("Import", type="primary"):
        with tempfile.NamedTemporaryFile(delete=False, suffix=Path(up.name).suffix) as f:
            f.write(up.read())
        text = R.extract_text(f.name)
        try:
            with st.spinner("Structuring your resume..."):
                prof = R.from_text(text)
        except llm.LLMUnavailable as e:
            st.warning(f"No AI provider ready ({e}). Set one up in step 4 and re-import. Using a minimal profile for now.")
            prof = R.heuristic_profile(text)
        save_profile(prof)
        st.rerun()
    if prof:
        st.subheader("Review & fix (every line here is a fact the CV may use)")
        c1, c2 = st.columns(2)
        prof.name = c1.text_input("Name", prof.name)
        prof.email = c2.text_input("Email", prof.email)
        prof.phone = c1.text_input("Phone", prof.phone)
        prof.location = c2.text_input("Location", prof.location)
        prof.links = [l for l in st.text_area("Links (one per line)", "\n".join(prof.links)).splitlines() if l.strip()]
        prof.summary = st.text_area("Summary (optional)", prof.summary)
        sk = st.text_area("Skills (one category per line, e.g. `Programming: Python, SQL`)",
                          "\n".join(f"{k}: {', '.join(v)}" for k, v in prof.skills.items()))
        prof.skills = {l.split(":", 1)[0].strip(): [s.strip() for s in l.split(":", 1)[1].split(",") if s.strip()] for l in sk.splitlines() if ":" in l}
        for e in prof.entries:
            with st.expander(f"{e.kind}: {e.title or e.org} @ {e.org}  ({len(e.bullets)} facts)"):
                e.org = st.text_input("Org / project", e.org, key=e.id + "o")
                e.title = st.text_input("Title", e.title, key=e.id + "t")
                for b in e.bullets:
                    b.text = st.text_area(b.id, b.text, key=b.id, height=70)
                    b.verified = st.checkbox("verified true", b.verified, key=b.id + "v")
        if st.button("Save profile", type="primary"):
            save_profile(prof)
            st.success("Saved")

elif page == STEPS[1]:
    st.header("What you want")
    p = cfg.preferences
    p.target_roles = [x.strip() for x in st.text_input("Target roles (comma separated)", ", ".join(p.target_roles)).split(",") if x.strip()]
    p.seniorities = st.multiselect("Seniority levels", C.SENIORITIES, p.seniorities)
    p.locations = [x.strip() for x in st.text_input("Countries/cities you can work from", ", ".join(p.locations)).split(",") if x.strip()]
    p.remote_worldwide = st.checkbox("Include worldwide-remote jobs (region-restricted ones like 'US only' are dropped)", p.remote_worldwide)
    p.require_paid = st.checkbox("Drop unpaid roles", p.require_paid)
    p.include_keywords = [x.strip() for x in st.text_input("Boost keywords (comma separated)", ", ".join(p.include_keywords)).split(",") if x.strip()]
    p.exclude_keywords = [x.strip() for x in st.text_input("Exclude title keywords", ", ".join(p.exclude_keywords)).split(",") if x.strip()]
    if st.button("Save", type="primary"):
        cfg.onboarded = True
        C.save_config(cfg)
        st.success("Saved")

elif page == STEPS[2]:
    st.header("Job sources")
    st.caption("All free and public. LinkedIn/Indeed/Glassdoor are not scraped (ban risk); use their alert emails instead.")
    from jobhunter.sources import REGISTRY
    s = cfg.sources
    s.enabled = st.multiselect("Enabled", [k for k in REGISTRY if k != "rss"], s.enabled)
    for ats in ("greenhouse", "lever", "ashby"):
        s.watchlist[ats] = [x.strip() for x in st.text_input(f"{ats} company slugs (comma separated; the bit in jobs.{ats}.io/<slug>)", ", ".join(s.watchlist.get(ats, []))).split(",") if x.strip()]
    s.extra_rss = [x for x in st.text_area("Extra RSS feeds (one per line)", "\n".join(s.extra_rss)).splitlines() if x.strip()]
    if st.button("Save", type="primary"):
        C.save_config(cfg)
        st.success("Saved")

elif page == STEPS[3]:
    st.header("AI provider (free options)")
    st.write("Used only to read your resume into structured data. Job scoring and CV tailoring work without any AI.")
    l = cfg.llm
    l.provider = st.selectbox("Provider", ["gemini", "groq", "openrouter", "ollama", "anthropic", "none"], ["gemini", "groq", "openrouter", "ollama", "anthropic", "none"].index(l.provider))
    help_ = {"gemini": "Free key: aistudio.google.com/apikey", "groq": "Free key: console.groq.com", "openrouter": "Free key: openrouter.ai (use :free models)",
             "ollama": "Local & fully free: install ollama.com and run `ollama pull llama3.1`", "anthropic": "Paid", "none": "No AI"}[l.provider]
    st.info(help_)
    l.model = st.text_input("Model (blank = default)", l.model, placeholder=DEFAULTS.get(l.provider, ("",))[0])
    if l.provider in DEFAULTS and DEFAULTS[l.provider][1]:
        secret_input("API key", DEFAULTS[l.provider][1])
    if st.button("Save & test", type="primary"):
        C.save_config(cfg)
        try:
            st.success("Works: " + llm.complete("Reply with one word.", "Say ok")[:40])
        except Exception as e:
            st.error(str(e))

elif page == STEPS[4]:
    st.header("Notifications")
    n = cfg.notify
    n.min_score = st.slider("Only notify for matches scoring at least", 0, 100, n.min_score)
    st.subheader("Telegram")
    n.telegram_enabled = st.checkbox("Enable Telegram", n.telegram_enabled)
    st.caption("Message @BotFather → /newbot → paste the token. Then send your bot any message and press Detect.")
    secret_input("Bot token", "TELEGRAM_BOT_TOKEN")
    n.telegram_chat_id = st.text_input("Chat id", n.telegram_chat_id)
    if st.button("Detect chat id"):
        from jobhunter.notify import find_telegram_chat_id
        try:
            n.telegram_chat_id = find_telegram_chat_id() or ""
            st.success(n.telegram_chat_id or "No messages found: message your bot first")
        except Exception as e:
            st.error(str(e))
    st.subheader("Email (Gmail API)")
    n.email_enabled = st.checkbox("Enable email", n.email_enabled)
    n.email_to = st.text_input("Send digests to", n.email_to or (prof.email if prof else ""))
    st.caption("Needs data/credentials.json from a free Google Cloud OAuth 'Desktop app' client (see README). First send opens a consent window.")
    c1, c2 = st.columns(2)
    if c1.button("Save", type="primary"):
        C.save_config(cfg)
        st.success("Saved")
    if c2.button("Send test message"):
        C.save_config(cfg)
        from jobhunter.notify import send_telegram
        try:
            if n.telegram_enabled:
                send_telegram("jobhunter test ✅")
            if n.email_enabled:
                from jobhunter.notify.gmail import send_email
                send_email(n.email_to, "jobhunter test", "It works.")
            st.success("Sent")
        except Exception as e:
            st.error(str(e))

elif page == STEPS[5]:
    st.header("Jobs & CVs")
    c1, c2 = st.columns(2)
    if c1.button("🔎 Find jobs now", type="primary"):
        with st.spinner("Searching all sources..."):
            st.session_state["stats"] = pipeline.run_discovery()
    if st.button("🧠 AI re-rank top matches (realistic fit)"):
        from jobhunter import ai
        with st.spinner("Reading the top postings against your profile..."):
            st.success(f"Re-ranked {ai.rerank_top(15)} jobs")
    if c2.button("📣 Send digest"):
        from jobhunter.notify import notify_all
        st.write(notify_all())
    if "stats" in st.session_state:
        s = st.session_state["stats"]
        st.caption(f"seen {s['seen']} · new {s['new']} · kept {s['kept']} · rejected {s['rejected']}")
        if s["errors"]:
            st.warning("Sources that failed (others still ran): " + ", ".join(f"{k}" for k in s["errors"]))
    rows = pipeline.top_jobs(0, 100)
    st.write(f"**{len(rows)} matches**")
    for r in rows:
        d = json.loads(r["score_json"] or "{}")
        with st.expander(f"{r['score']:.0f} · {r['title']} @ {r['company']} · {r['location'] or 'Remote'}"):
            st.write(f"[Open posting]({r['url']})  ·  seniority: {d.get('seniority')}  ·  matched skills: {', '.join(d.get('matched_skills', [])) or '-'}")
            st.write((r["description"] or "")[:600] + "…")
            if d.get("llm"):
                a = d["llm"]
                st.info(f"**AI fit {a['fit']:.0f}** — {a.get('one_line', '')}")
                st.write("✅ " + "; ".join(a.get("matches", [])[:3]))
                if a.get("gaps"): st.write("⚠️ gaps: " + "; ".join(a["gaps"][:3]))
                if a.get("red_flags"): st.error("🚩 " + "; ".join(a["red_flags"]))
            b1, b2, b3 = st.columns(3)
            if prof and b2.button("✉️ Cover letter", key=f"c{r['id']}"):
                from jobhunter import ai
                with st.spinner("Writing and fact-checking..."):
                    res = ai.cover_letter(prof, dict(r), None)
                st.text_area("Cover letter", res["text"], height=300, key=f"cl{r['id']}")
                if res["problems"]: st.warning("Unresolved checks: " + "; ".join(res["problems"]))
            if prof and b3.button("📝 Prepare application (does NOT submit)", key=f"p{r['id']}"):
                from jobhunter.apply import prepare_application
                with st.spinner("Tailoring, writing, pre-filling the real form..."):
                    out = prepare_application(r["id"], headless=True, progress=lambda *_: None)
                st.success(f"Prepared application #{out['application_id']}: {out['filled']} fields filled, {len(out['needs_user'])} need you. Review it in step 7.")
            if prof and b1.button("Tailor CV", key=f"t{r['id']}"):
                from jobhunter.cv import tailor
                out = tailor(prof, dict(r))
                st.write("Skills the job asks for that your profile does **not** show (not added):", out["gaps"] or "none")
                if out["pdf"]:
                    st.download_button("Download PDF", Path(out["pdf"]).read_bytes(), file_name=f"cv_{r['id']}.pdf")
                else:
                    st.warning("Install Tectonic to compile the PDF. LaTeX saved at " + out["tex"])
                    st.download_button("Download .tex", Path(out["tex"]).read_text(encoding="utf-8"), file_name=f"cv_{r['id']}.tex")


elif page == STEPS[6]:
    from jobhunter.apply import approval
    st.header("Applications awaiting your approval")
    st.caption("Nothing is sent from here. Approve, then run `jobhunter submit <id>` in a terminal: it re-checks everything and asks one last time.")
    c = db.conn()
    for a in c.execute("SELECT a.*, j.title, j.company, j.url FROM applications a JOIN jobs j ON j.id=a.job_id ORDER BY a.id DESC").fetchall():
        snap = json.loads(a["snapshot_json"] or "{}")
        with st.expander(f"#{a['id']} · {a['title']} @ {a['company']} · {a['approval_status']}"):
            st.write(f"[Open posting]({a['url']})")
            if a["screenshot"] and Path(a["screenshot"]).exists():
                st.image(a["screenshot"], caption="How the form looked after pre-fill")
            st.table([{"field": f["label"][:50], "value": f["value"][:80], "source": f["source"][:40]} for f in snap.get("filled", [])])
            for n in snap.get("needs_user", []):
                st.warning(f"You must answer: **{n['label']}** ({n['reason']})")
            if a["cover_text"]:
                st.text_area("Cover letter", a["cover_text"], height=240, key=f"ct{a['id']}", disabled=True)
            if a["approval_status"] in ("pending", "rejected"):
                k1, k2 = st.columns(2)
                if k1.button("✅ Approve", key=f"ap{a['id']}"):
                    approval.approve(a["id"]); st.rerun()
                if k2.button("❌ Reject", key=f"rj{a['id']}"):
                    approval.reject(a["id"]); st.rerun()
            elif a["approval_status"] == "approved":
                st.success(f"Approved. Submit with:  jobhunter submit {a['id']}")
