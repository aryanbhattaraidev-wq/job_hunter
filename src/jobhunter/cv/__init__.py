"""CV tailoring = SELECT (reorder/choose real facts) -> VALIDATE (every ID/skill exists) -> RENDER LaTeX -> COMPILE.

The model never writes free text into the CV, so nothing can be fabricated. Gaps are reported, never filled.
"""
from __future__ import annotations
import os, re, shutil, subprocess, json
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from ..config import ARTIFACTS
from ..profile import Profile

TEMPLATES = Path(__file__).resolve().parent / "templates"
_ESC = {"&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
        "~": r"\textasciitilde{}", "^": r"\textasciicircum{}", "\\": r"\textbackslash{}"}


def tex_escape(s: str) -> str:
    return "".join(_ESC.get(ch, ch) for ch in str(s or ""))


STOP = set("the and for with that this from have has are you our will your about into over more using used use built build work working team new per via also all any can".split())


def tokens(s: str) -> set[str]:
    return set(re.findall(r"[a-z][a-z0-9+#.]{1,}", s.lower()))


def plan(prof: Profile, job: dict, max_bullets: int = 4, max_projects: int = 3) -> dict:
    """Deterministic, explainable selection driven by overlap with the job text."""
    jt = tokens(f"{job['title']} {job.get('description', '')}")
    tech = {t for sk in prof.skill_set() for t in tokens(sk)} | {t for e in prof.entries for x in e.tech for t in tokens(x)}
    def rel(text: str, extra: str = "") -> int:
        hit = tokens(text + " " + extra) & jt - STOP
        return sum(3 if t in tech else 1 for t in hit)  # real skills/tech count triple vs generic words
    chosen, omitted = [], []
    exp = [e for e in prof.entries if e.kind == "experience"]
    proj = sorted([e for e in prof.entries if e.kind != "experience"], key=lambda e: -rel(e.org + " " + " ".join(e.tech) + " ".join(b.text for b in e.bullets)))
    for e in exp + proj[:max_projects]:
        bl = sorted([b for b in e.bullets if b.verified], key=lambda b: -rel(b.text, " ".join(b.skills)))
        keep = bl[:max_bullets if e.kind == "experience" else 2]
        # keep original chronological order within an entry for readability
        order = {b.id: i for i, b in enumerate(e.bullets)}
        chosen.append({"id": e.id, "bullets": [b.id for b in sorted(keep, key=lambda b: order[b.id])]})
        omitted += [b.id for b in e.bullets if b not in keep]
    skills = {cat: sorted(v, key=lambda s: (s.lower() not in jt, v.index(s))) for cat, v in prof.skills.items()}
    demanded = tokens(job.get("description", "")) & {"kubernetes", "aws", "azure", "gcp", "docker", "spark", "java", "go", "rust", "typescript", "react", "tensorflow", "pytorch", "langchain", "langgraph", "rag", "llm", "sql", "fastapi", "airflow", "mlops", "c++"}
    have = prof.skill_set() | tokens(prof.text_blob())
    gaps = sorted(d for d in demanded if d not in have)
    covered = sorted(d for d in demanded if d in have)
    return {"entries": chosen, "skills": skills, "omitted": omitted, "gaps": gaps, "covered": covered}


def validate(prof: Profile, pl: dict) -> list[str]:
    """Hard guarantee: only facts that exist in the profile can appear."""
    errs = []
    bullets = prof.all_bullets()
    eids = {e.id for e in prof.entries}
    for e in pl["entries"]:
        if e["id"] not in eids:
            errs.append(f"unknown entry {e['id']}")
        for b in e["bullets"]:
            if b not in bullets or not bullets[b].verified:
                errs.append(f"unknown/unverified bullet {b}")
    for cat, ss in pl["skills"].items():
        for s in ss:
            if s.lower() not in prof.skill_set():
                errs.append(f"skill not in profile: {s}")
    return errs


def render(prof: Profile, pl: dict) -> str:
    env = Environment(loader=FileSystemLoader(TEMPLATES), block_start_string="\\BLOCK{", block_end_string="}",
                      variable_start_string="\\VAR{", variable_end_string="}", comment_start_string="\\#{",
                      comment_end_string="}", trim_blocks=True, autoescape=False)
    env.filters["e"] = tex_escape
    bl = prof.all_bullets()
    sel = {e["id"]: e["bullets"] for e in pl["entries"]}
    entries = {e.id: e for e in prof.entries}
    experience = [(entries[i], [bl[b] for b in sel[i]]) for i in sel if entries[i].kind == "experience"]
    projects = [(entries[i], [bl[b] for b in sel[i]]) for i in sel if entries[i].kind != "experience"]
    return env.get_template("cv.tex.j2").render(p=prof, experience=experience, projects=projects, skills=pl["skills"])


def compile_pdf(tex_path: Path) -> Path | None:
    """Compile with tectonic (preferred, single binary) or pdflatex/xelatex. Returns pdf path or None."""
    local = Path(__file__).resolve().parents[3] / "tools" / "tectonic.exe"
    if local.exists():
        os.environ["PATH"] = str(local.parent) + os.pathsep + os.environ["PATH"]
    for exe, args in (("tectonic", ["tectonic", "-X", "compile", "--outdir", str(tex_path.parent), str(tex_path)]),
                      ("pdflatex", ["pdflatex", "-interaction=nonstopmode", "-output-directory", str(tex_path.parent), str(tex_path)])):
        if shutil.which(exe):
            r = subprocess.run(args, capture_output=True, text=True, timeout=180)
            pdf = tex_path.with_suffix(".pdf")
            if pdf.exists():
                return pdf
    return None


def tailor(prof: Profile, job: dict) -> dict:
    pl = plan(prof, job)
    errs = validate(prof, pl)
    if errs:
        raise ValueError("CV plan failed validation: " + "; ".join(errs))
    out = ARTIFACTS / str(job.get("id", "adhoc"))
    out.mkdir(parents=True, exist_ok=True)
    tex = out / "cv.tex"
    tex.write_text(render(prof, pl), encoding="utf-8")
    pdf = compile_pdf(tex)
    (out / "report.json").write_text(json.dumps({k: pl[k] for k in ("gaps", "covered", "omitted")}, indent=2), encoding="utf-8")
    return {"tex": str(tex), "pdf": str(pdf) if pdf else None, "gaps": pl["gaps"], "covered": pl["covered"]}
