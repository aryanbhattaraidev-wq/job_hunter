import re
from pathlib import Path
import pytest
from jobhunter import db, resume_import as R
from jobhunter.apply import approval, form
from tests.test_core import RESUME_JSON

FORM = """<html><body><form id=f onsubmit="document.title='SUBMITTED'; return false;">
<label for=fn>First Name *</label><input id=fn required>
<label for=ln>Last Name *</label><input id=ln required>
<label for=em>Email *</label><input id=em type=email required>
<label for=ph>Phone</label><input id=ph>
<label for=li>LinkedIn Profile</label><input id=li>
<label for=gh>GitHub</label><input id=gh>
<label for=why>Why do you want to work here? *</label><textarea id=why required></textarea>
<label for=gen>Gender</label><select id=gen><option>Prefer not to say</option></select>
<label for=sal>Salary expectations *</label><input id=sal required>
<label for=pet>Favourite pet *</label><input id=pet required>
<fieldset><legend>Are you legally authorized to work in the United States? *</legend>
<label><input type=radio name=auth value=y>Yes</label><label><input type=radio name=auth value=n>No</label></fieldset>
<label>Resume/CV <input type=file id=cv></label>
<button type=submit>Submit Application</button></form></body></html>"""


@pytest.fixture
def prof():
    p = R.build_profile(RESUME_JSON)
    p.links = ["https://linkedin.com/in/test", "github.com/test"]
    return p


@pytest.fixture
def page():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        try:
            b = p.chromium.launch(channel="msedge", headless=True)
        except Exception:
            pytest.skip("Edge not available")
        pg = b.new_page()
        pg.set_content(FORM)
        yield pg
        b.close()


def test_prefill_fills_known_flags_sensitive_and_never_submits(page, prof, tmp_path):
    cv = tmp_path / "cv.pdf"; cv.write_bytes(b"%PDF-1.4 fake")
    res = form.prefill(page, prof, str(cv), None, "")
    assert page.input_value("#fn") == "Test" and page.input_value("#ln") == "User"
    assert page.input_value("#em") == "t@example.com"
    assert page.input_value("#li") == "https://linkedin.com/in/test" and page.input_value("#gh") == "https://github.com/test"
    needs = {n["label"].strip(" *"): n["reason"] for n in res["needs_user"]}
    assert "Salary expectations" in needs and "sensitive" in needs["Salary expectations"]   # never auto-answered
    assert "Gender" in needs
    assert any("authorized to work" in k for k in needs)                                    # radio questions are flagged, never skipped
    assert "Favourite pet" in needs                                                         # unknown required -> human
    assert page.input_value("#sal") == "" and page.input_value("#pet") == ""
    assert "Why do you want" in " ".join(needs)                                             # no drafter -> left for human
    assert page.title() != "SUBMITTED"                                                      # the form was NOT submitted
    assert any(f["source"] == "cv" for f in res["filled"])


def test_drafter_answer_is_used_and_marked(page, prof):
    res = form.prefill(page, prof, None, None, "", drafter=lambda q: "I like agents.")
    assert page.input_value("#why") == "I like agents."
    assert any("REVIEW" in f["source"] for f in res["filled"])


@pytest.fixture
def tmpdb(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(db, "DATA", tmp_path)
    c = db.conn()
    c.execute("INSERT INTO jobs(fingerprint,title,company,url) VALUES('f','t','c','http://x')")
    c.execute("INSERT INTO applications(job_id,cover_text,snapshot_json,created_at) VALUES(1,'letter','{\"filled\":[]}','now')")
    c.commit()
    return c


def test_approval_binds_to_content(tmpdb):
    with pytest.raises(PermissionError):
        approval.assert_approved(approval.get(tmpdb, 1))                  # pending -> cannot submit
    approval.approve(1)
    approval.assert_approved(approval.get(db.conn(), 1))                  # approved + unchanged -> ok
    c = db.conn(); c.execute("UPDATE applications SET cover_text='CHANGED' WHERE id=1"); c.commit()
    with pytest.raises(PermissionError):
        approval.assert_approved(approval.get(c, 1))                      # edited after approval -> invalid


def test_rejected_cannot_submit(tmpdb):
    approval.reject(1)
    with pytest.raises(PermissionError):
        approval.assert_approved(approval.get(db.conn(), 1))


def test_only_submit_module_can_click_submit():
    src = Path(__file__).resolve().parents[1] / "src" / "jobhunter"
    offenders = []
    for f in src.rglob("*.py"):
        if f.name == "submit.py" and f.parent.name == "apply":
            continue
        txt = f.read_text(encoding="utf-8")
        if re.search(r"SUBMIT_BUTTON|click\([^)]*[Ss]ubmit|\.submit\(\)|requestSubmit|dispatchEvent\([^)]*submit", txt):
            offenders.append(str(f))
    assert offenders == []


def test_scheduler_path_never_imports_submit():
    cli = (Path(__file__).resolve().parents[1] / "src" / "jobhunter" / "cli.py").read_text(encoding="utf-8")
    run_body = cli[cli.index("def run()"):cli.index("def schedule")]
    assert "submit_application" not in run_body and "apply.submit" not in run_body
