"""LLM-assisted steps. Every one is optional, grounded in the profile, and validated in code.

rerank   : fast/free model re-reads top matches and gives a realistic fit (catches '5+ years' hidden in a junior title)
brief    : short company/role brief from the posting text only (no outside claims)
cover    : cover letter by the smart model; every sentence cites profile fact IDs; numbers and skills are verified
"""
from __future__ import annotations
import json, re, time
from pathlib import Path
from . import db, llm
from .config import ARTIFACTS, load_config
from .cv import tex_escape, tokens
from .profile import Profile

TECH_VOCAB = {"kubernetes", "aws", "azure", "gcp", "docker", "spark", "java", "golang", "rust", "typescript", "react", "tensorflow", "pytorch",
              "langchain", "langgraph", "rag", "sql", "fastapi", "airflow", "mlops", "scala", "kafka", "terraform", "pandas", "numpy", "redis",
              "django", "flask", "nodejs", "graphql", "snowflake", "databricks", "hadoop", "cuda", "triton", "vllm", "llamaindex", "pinecone"}


def compact_profile(prof: Profile, with_ids: bool = False) -> str:
    out = [f"Name: {prof.name}", "Skills: " + "; ".join(f"{k}: {', '.join(v)}" for k, v in prof.skills.items())]
    for e in prof.entries:
        out.append(f"[{e.kind}] {e.title} @ {e.org} ({e.start}-{e.end})")
        for b in e.bullets:
            out.append(("  " + (f"{b.id}: " if with_ids else "- ")) + b.text)
    for b in prof.extras:
        out.append((f"{b.id}: " if with_ids else "- ") + b.text)
    return "\n".join(out)


# ---------------------------------------------------------------- rerank
RERANK_SYS = """You evaluate how well a job fits a candidate. Be realistic and skeptical, not flattering.
Return JSON: {"fit":0-100,"realistic_seniority":"intern|trainee|junior|mid|senior|lead","years_required":number|null,
"paid":true|false|null,"open_to_nepal_or_worldwide_remote":true|false|null,
"matches":[short],"gaps":[short],"red_flags":[short],"one_line":"why this score"}
Judge years_required from the whole posting (e.g. '5+ years' means senior no matter the title). """ + llm.UNTRUSTED


def rerank_job(prof: Profile, job: dict) -> dict:
    user = f"<candidate>\n{compact_profile(prof)}\n</candidate>\n<untrusted>\nTitle: {job['title']}\nCompany: {job['company']}\nLocation: {job['location']}\n{job['description'][:6000]}\n</untrusted>"
    d = llm.complete_json(RERANK_SYS, user)
    d["fit"] = max(0, min(100, float(d.get("fit") or 0)))
    return d


def blend(rule_score: float, a: dict) -> float:
    s = 0.5 * rule_score + 0.5 * a["fit"]
    yrs = a.get("years_required")
    if a.get("realistic_seniority") in ("senior", "lead") or (isinstance(yrs, (int, float)) and yrs >= 5):
        s *= 0.5
    if a.get("paid") is False:
        s *= 0.5
    if a.get("open_to_nepal_or_worldwide_remote") is False:
        s *= 0.4
    return round(s, 1)


def rerank_top(limit: int = 25, min_rule_score: float = 35, pause: float = 4.0, progress=lambda *_: None) -> int:
    """Re-rank jobs that have not been analysed yet. Free-tier friendly (paced)."""
    from .profile import load_profile
    prof = load_profile()
    if not prof or not llm.available():
        return 0
    c = db.conn()
    rows = c.execute("SELECT * FROM jobs WHERE status='scored' AND score>=? AND score_json NOT LIKE '%\"llm\"%' ORDER BY score DESC LIMIT ?",
                     (min_rule_score, limit)).fetchall()
    n = 0
    for r in rows:
        try:
            a = rerank_job(prof, dict(r))
        except Exception as e:
            progress("error", r["id"], e)
            continue
        d = json.loads(r["score_json"] or "{}")
        d["rule_score"] = r["score"]
        d["llm"] = a
        c.execute("UPDATE jobs SET score=?, score_json=? WHERE id=?", (blend(r["score"], a), json.dumps(d), r["id"]))
        c.commit()
        n += 1
        time.sleep(pause)
    return n


# ---------------------------------------------------------------- company brief
BRIEF_SYS = """From ONLY the posting text, write a brief for a job applicant.
Return JSON: {"company_does":str,"role_summary":str,"tech_stack":[str],"talking_points":[str],"questions_to_ask":[str],"unknown":[str]}
Do not add outside knowledge about the company; list what the posting does not reveal under "unknown". """ + llm.UNTRUSTED


def company_brief(job: dict) -> dict:
    user = f"<untrusted>\nCompany: {job['company']}\nTitle: {job['title']}\n{job['description'][:7000]}\n</untrusted>"
    return llm.complete_json(BRIEF_SYS, user)


# ---------------------------------------------------------------- cover letter
COVER_SYS = """Write a concise, specific cover letter (150-250 words, 3 short paragraphs, no clichés like 'I am writing to apply').
Use ONLY facts from the candidate facts list. Every paragraph must cite the fact IDs it relies on.
Never invent employers, numbers, technologies, titles or achievements. If the job wants something the candidate lacks, do not claim it;
you may express eagerness to learn it. Plain, confident, human tone.
Return JSON: {"paragraphs":[{"text":str,"fact_ids":[str]}]} (no greeting or sign-off; those are added for you).
""" + llm.UNTRUSTED


def _pretty(company: str) -> str:
    """ATS sources give slugs like 'unstructured'; make them presentable without inventing anything."""
    return (company.title() if company and company == company.lower() and " " not in company else company) or "your company"


def _numbers(s: str) -> set[str]:
    return set(re.findall(r"\d+(?:[.,]\d+)?", s))


def check_letter(prof: Profile, paras: list[dict]) -> list[str]:
    errs = []
    facts = prof.all_bullets()
    entry_blob = " ".join(f"{e.title} {e.org} {e.start} {e.end}" for e in prof.entries) + " " + " ".join(prof.skill_set())
    allowed_tokens = tokens(entry_blob + " " + prof.text_blob())
    total = 0
    for i, p in enumerate(paras):
        ids = p.get("fact_ids") or []
        text = p.get("text", "")
        total += len(text.split())
        if not ids:
            errs.append(f"paragraph {i+1} cites no fact ids")
        bad = [x for x in ids if x not in facts]
        if bad:
            errs.append(f"paragraph {i+1} cites unknown ids {bad}")
        cited = " ".join(facts[x].text for x in ids if x in facts) + " " + entry_blob
        extra_nums = _numbers(text) - _numbers(cited)
        if extra_nums:
            errs.append(f"paragraph {i+1} contains numbers not in cited facts: {sorted(extra_nums)}")
    letter_tokens = tokens(" ".join(p.get("text", "") for p in paras))
    invented = sorted(t for t in letter_tokens & TECH_VOCAB if t not in allowed_tokens)
    if invented:
        errs.append(f"mentions technologies not in the profile: {invented}")
    if total > 300:
        errs.append(f"too long ({total} words)")
    return errs


def cover_letter(prof: Profile, job: dict, brief: dict | None = None) -> dict:
    jd_tokens = tokens(job["description"])
    user = (f"<facts>\n{compact_profile(prof, with_ids=True)}\n</facts>\n"
            f"Company brief (from posting): {json.dumps(brief or {})[:1500]}\n"
            f"<untrusted>\nTitle: {job['title']} at {job['company']}\n{job['description'][:5000]}\n</untrusted>")
    errs: list[str] = []
    for attempt in range(3):
        msg = user + ("\n\nFix these problems from your previous attempt:\n- " + "\n- ".join(errs) if errs else "")
        d = llm.complete_json(COVER_SYS, msg, smart=True)
        paras = d.get("paragraphs") or []
        errs = check_letter(prof, paras)
        if not errs:
            break
    body = "\n\n".join(p["text"] for p in paras)
    letter = f"Dear Hiring Team at {_pretty(job['company'])},\n\n{body}\n\nSincerely,\n{prof.name}\n{prof.email} | {prof.phone}"
    out = ARTIFACTS / str(job["id"])
    out.mkdir(parents=True, exist_ok=True)
    (out / "cover_letter.txt").write_text(letter, encoding="utf-8")
    (out / "cover_letter.json").write_text(json.dumps({"paragraphs": paras, "problems": errs}, indent=2), encoding="utf-8")
    pdf = _letter_pdf(prof, job, body, out)
    return {"text": letter, "path": str(out / "cover_letter.txt"), "pdf": str(pdf) if pdf else None, "problems": errs}


def _letter_pdf(prof: Profile, job: dict, body: str, out: Path):
    from .cv import compile_pdf
    paras = "\n\n".join(tex_escape(p) for p in body.split("\n\n"))
    tex = (r"\documentclass[11pt]{article}\usepackage[T1]{fontenc}\usepackage{lmodern}\usepackage[margin=1in]{geometry}\pagestyle{empty}"
           r"\setlength{\parindent}{0pt}\setlength{\parskip}{8pt}\begin{document}" + "\n"
           + tex_escape(prof.name) + r"\\" + tex_escape(prof.email + " | " + prof.phone) + "\n\n"
           + "Dear Hiring Team at " + tex_escape(_pretty(job["company"])) + ",\n\n" + paras
           + "\n\nSincerely,\n\n" + tex_escape(prof.name) + "\n" + r"\end{document}")
    p = out / "cover_letter.tex"
    p.write_text(tex, encoding="utf-8")
    return compile_pdf(p)
