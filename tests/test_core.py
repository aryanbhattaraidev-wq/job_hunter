import pytest
from jobhunter import pipeline, resume_import as R
from jobhunter.config import Preferences
from jobhunter.cv import plan, validate, render, tex_escape

RESUME_JSON = {
    "name": "Test User", "email": "t@example.com", "phone": "123", "location": "Kathmandu, Nepal", "links": ["github.com/x"],
    "skills": {"Programming": ["Python", "SQL"], "AI": ["LangGraph", "FastAPI", "PyTorch"]},
    "entries": [
        {"kind": "experience", "org": "Acme & Co", "title": "AI Engineer Trainee", "start": "2026", "end": "", "location": "Nepal",
         "tech": ["Python"], "bullets": ["Built a LangGraph agent pipeline with 50% fewer errors", "Wrote tests for the C++ service"]},
        {"kind": "project", "org": "Retina_Detector", "title": "", "tech": ["PyTorch"], "bullets": ["Built a PyTorch classifier"]},
    ],
    "education": [{"school": "KEC", "degree": "BE", "start": "", "end": "2026", "location": "Lalitpur"}],
    "extras": ["Publication in InJET 2026"],
}
P = Preferences()


def job(title, desc="", loc="Remote", remote=True, company="X"):
    return dict(title=title, description=desc, location=loc, remote=remote, company=company, url="http://x", source="t")


def test_prefilter_accepts_junior_ai_remote():
    assert pipeline.prefilter(job("Junior AI Engineer", "python llm"), P) is None


def test_prefilter_rejects_senior_unpaid_geo_and_offtopic():
    assert "seniority" in pipeline.prefilter(job("Senior AI Engineer"), P)
    assert pipeline.prefilter(job("AI Engineer Intern", "this is an unpaid internship"), Preferences(seniorities=["internship"])) == "unpaid"
    assert pipeline.prefilter(job("AI Engineer", "Remote, US only. Must be based in the US"), P)
    assert pipeline.prefilter(job("Pastry Chef"), P)


def test_worldwide_remote_ok_even_with_us_mention():
    assert pipeline.prefilter(job("AI Engineer", "work from anywhere", loc="Worldwide"), P) is None


def test_nepal_location_counts():
    assert pipeline.prefilter(job("ML Engineer", "", loc="Kathmandu, Nepal", remote=False), P) is None


def test_scoring_prefers_skill_overlap():
    prof = R.build_profile(RESUME_JSON)
    hi, _ = pipeline.score(job("AI Engineer", "python langgraph fastapi pytorch sql llm"), prof, P)
    lo, _ = pipeline.score(job("AI Engineer", "java kubernetes"), prof, P)
    assert hi > lo


def test_cv_only_real_facts_and_gaps():
    prof = R.build_profile(RESUME_JSON)
    j = job("AI Engineer", "We need LangGraph, kubernetes and aws experience")
    pl = plan(prof, j)
    assert validate(prof, pl) == []
    assert "kubernetes" in pl["gaps"] and "aws" in pl["gaps"]
    tex = render(prof, pl)
    assert "kubernetes" not in tex.lower()
    assert r"Acme \& Co" in tex and r"Retina\_Detector" in tex


def test_validator_catches_fabrication():
    prof = R.build_profile(RESUME_JSON)
    pl = plan(prof, job("AI Engineer"))
    pl["skills"]["AI"].append("Kubernetes")
    pl["entries"][0]["bullets"].append("made_up_id")
    errs = validate(prof, pl)
    assert len(errs) == 2


def test_tex_escape_specials():
    assert tex_escape("100% & #1_a $5 {x}") == r"100\% \& \#1\_a \$5 \{x\}"


def test_region_tagged_remote_rejected():
    assert pipeline.prefilter(job("AI Engineer", "", loc="Remote - US"), P)
    assert pipeline.prefilter(job("AI Engineer", "", loc="Remote - Worldwide"), P) is None


def test_build_profile_tolerates_nulls():
    prof = R.build_profile({"name": None, "entries": [{"org": "A", "start": None, "end": None, "bullets": ["x", None]}], "skills": None, "education": [{"school": "S", "start": None}]})
    assert prof.entries[0].start == "" and len(prof.entries[0].bullets) == 1


def test_alert_email_parsing():
    from jobhunter.sources.alerts import parse_alert_html
    html = '''<table><tr><td><a href="https://www.linkedin.com/comm/jobs/view/123?trk=x">AI Engineer</a><br>Acme Corp<br>Remote</td></tr>
    <tr><td><a href="https://www.linkedin.com/comm/jobs/view/123?trk=y">AI Engineer</a></td></tr>
    <tr><td><a href="https://www.linkedin.com/comm/jobs/view/456">Junior ML Engineer</a><br>Beta Inc<br>Kathmandu</td></tr>
    <tr><td><a href="https://www.linkedin.com/help/unsubscribe">Unsubscribe</a></td></tr></table>'''
    jobs = parse_alert_html(html)
    assert [j["title"] for j in jobs] == ["AI Engineer", "Junior ML Engineer"]   # deduped, noise dropped
    assert jobs[0]["company"] == "Acme Corp" and jobs[0]["remote"] and jobs[1]["location"] == "Kathmandu"


def test_clearance_or_citizen_requirement_rejected():
    assert pipeline.prefilter(job("AI Engineer", "Remote. Active security clearance required; US citizen only."), P)
