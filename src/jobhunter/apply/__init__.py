"""prepare_application: tailor CV + cover letter, pre-fill the real form, screenshot it, queue it for YOUR approval."""
from __future__ import annotations
import json
from .. import ai, db, llm
from ..config import ARTIFACTS
from ..cv import tailor
from ..profile import load_profile
from . import form

DRAFT_SYS = """Answer ONE job-application question for the candidate in 40-120 words, first person, specific, honest.
Use ONLY the candidate facts. Return JSON {"text":str,"fact_ids":[str]}. """ + llm.UNTRUSTED


def make_drafter(prof, job):
    if not llm.available():
        return None

    def draft(question: str):
        user = (f"<facts>\n{ai.compact_profile(prof, with_ids=True)}\n</facts>\n"
                f"<untrusted>\nJob: {job['title']} at {job['company']}\nQuestion: {question}\n</untrusted>")
        try:
            d = llm.complete_json(DRAFT_SYS, user)
        except Exception:
            return None
        if ai.check_letter(prof, [d]):      # same fabrication checks as the cover letter; failing drafts are left for the human
            return None
        return d.get("text")
    return draft


def prepare_application(job_id: int, headless: bool = True, progress=print) -> dict:
    from playwright.sync_api import sync_playwright
    prof = load_profile()
    if not prof:
        raise RuntimeError("No profile yet")
    c = db.conn()
    job = dict(c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())
    progress("tailoring CV...")
    cv = tailor(prof, job)
    cover_text, cover_pdf, problems = "", None, []
    if llm.available():
        progress("writing cover letter...")
        brief = None
        try:
            brief = ai.company_brief(job)
        except Exception:
            pass
        r = ai.cover_letter(prof, job, brief)
        cover_text, cover_pdf, problems = r["text"], r["pdf"], r["problems"]
    progress(f"opening {job['url']} ...")
    out = ARTIFACTS / str(job_id)
    out.mkdir(parents=True, exist_ok=True)
    shot = out / "prefilled.png"
    with sync_playwright() as p:
        ctx = form.open_browser(p, headless=headless)
        try:
            page = ctx.new_page()
            form.goto_form(page, job["url"])
            res = form.prefill(page, prof, cv["pdf"], cover_pdf, cover_text, drafter=make_drafter(prof, job))
            page.screenshot(path=str(shot), full_page=True)
        finally:
            ctx.close()
    snap = json.dumps({"filled": res["filled"], "needs_user": res["needs_user"]}, sort_keys=True)
    cur = c.execute("""INSERT INTO applications(job_id,cv_pdf,cover_pdf,cover_text,snapshot_json,needs_user_json,screenshot,created_at)
                       VALUES(?,?,?,?,?,?,?,?)""", (job_id, cv["pdf"], cover_pdf, cover_text, snap, json.dumps(res["needs_user"]), str(shot), db.now()))
    db.log(c, job_id, "prepared", {"application": cur.lastrowid})
    c.commit()
    return {"application_id": cur.lastrowid, "filled": len(res["filled"]), "needs_user": res["needs_user"], "cover_problems": problems,
            "cv_pdf": cv["pdf"], "cv_tex": cv["tex"], "gaps": cv["gaps"], "screenshot": str(shot)}
