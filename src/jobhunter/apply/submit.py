"""THE ONLY place in the codebase that is allowed to click a submit button.

A test asserts that no other module contains submit-click code. Submission requires: (1) an approved application whose
content hash is unchanged, (2) the form re-filled by the same code reproducing the SAME snapshot, (3) an explicit
confirmation callback from the human at the very last moment. It can never run from the scheduler.
"""
from __future__ import annotations
import json
from pathlib import Path
from .. import db
from ..config import ARTIFACTS
from ..profile import load_profile
from . import approval, form

SUBMIT_BUTTON = "button[type=submit], input[type=submit], button:has-text('Submit application'), button:has-text('Submit Application'), button:has-text('Submit')"


def submit_application(app_id: int, confirm, headless: bool = False) -> dict:
    """confirm(summary:str)->bool is called right before the click. Returns {'submitted': bool, ...}."""
    from playwright.sync_api import sync_playwright
    c = db.conn()
    app = approval.get(c, app_id)
    approval.assert_approved(app)
    job = dict(c.execute("SELECT * FROM jobs WHERE id=?", (app["job_id"],)).fetchone())
    prof = load_profile()
    with sync_playwright() as p:
        ctx = form.open_browser(p, headless=headless)
        try:
            page = ctx.new_page()
            form.goto_form(page, job["url"])
            saved = json.loads(app["snapshot_json"])
            approved_answers = {f["label"]: f["full"] for f in saved["filled"] if f.get("full")}   # replay the exact approved drafts
            res = form.prefill(page, prof, app["cv_pdf"], app["cover_pdf"], app["cover_text"] or "", drafter=approved_answers.get)
            replay = {"filled": res["filled"], "needs_user": res["needs_user"]}
            if [(f["label"], f["value"]) for f in replay["filled"]] != [(f["label"], f["value"]) for f in saved["filled"]]:
                return {"submitted": False, "reason": "form changed since approval; run prefill again and re-approve"}
            if replay["needs_user"]:
                missing = [n["label"] for n in replay["needs_user"] if n.get("required")]
                if missing:
                    print("Fields you must complete by hand in the open window:", missing)
            summary = f"{job['title']} @ {job['company']}  ->  {job['url']}"
            if not confirm(summary):
                return {"submitted": False, "reason": "declined at final confirmation"}
            page.click(SUBMIT_BUTTON, timeout=10000)
            page.wait_for_timeout(4000)
            shot = ARTIFACTS / str(job["id"]) / "submitted.png"
            page.screenshot(path=str(shot), full_page=True)
        finally:
            ctx.close()
    c.execute("UPDATE applications SET approval_status='submitted', submitted_at=? WHERE id=?", (db.now(), app_id))
    c.execute("UPDATE jobs SET status='applied' WHERE id=?", (job["id"],))
    db.log(c, job["id"], "submitted", {"application": app_id})
    c.commit()
    return {"submitted": True, "proof": str(shot)}
