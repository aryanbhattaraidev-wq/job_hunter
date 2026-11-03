"""Turn ANY resume (PDF/txt) into a structured Profile with stable fact IDs."""
from __future__ import annotations
import re
from pathlib import Path
from pypdf import PdfReader
from . import llm
from .profile import Profile, Entry, Bullet, Education, slug

SYSTEM = """You convert a resume into JSON. Copy facts EXACTLY; never invent, embellish or add anything not in the text.
Schema: {"name","email","phone","location","links":[str],"summary":str,
"skills":{category:[skill]},
"entries":[{"kind":"experience|project","org","title","start","end","location","tech":[str],"bullets":[str]}],
"education":[{"school","degree","start","end","location"}],
"extras":[str]}
extras = publications, certifications, awards; one string each. For projects, org = project name.
""" + llm.UNTRUSTED


def extract_text(path: str | Path) -> str:
    p = Path(path)
    if p.suffix.lower() == ".pdf":
        return "\n".join((pg.extract_text() or "") for pg in PdfReader(str(p)).pages)
    return p.read_text(encoding="utf-8", errors="ignore")


def from_text(text: str) -> Profile:
    data = llm.complete_json(SYSTEM, f"<untrusted>\n{text[:20000]}\n</untrusted>")
    return build_profile(data)


def _s(x) -> str:
    return "" if x is None else str(x)


def _l(x) -> list:
    return [] if x is None else list(x)


def build_profile(d: dict) -> Profile:
    """Tolerant of LLM output: nulls become empty values, wrong types are coerced."""
    entries = []
    for i, e in enumerate(_l(d.get("entries"))):
        kind = _s(e.get("kind")) or "experience"
        eid = f"{kind[:3]}_{slug(_s(e.get('org')))}_{i}"
        entries.append(Entry(id=eid, kind=kind, org=_s(e.get("org")), title=_s(e.get("title")),
                             start=_s(e.get("start")), end=_s(e.get("end")), location=_s(e.get("location")),
                             tech=[_s(t) for t in _l(e.get("tech"))],
                             bullets=[Bullet(id=f"{eid}_b{j}", text=_s(t)) for j, t in enumerate(_l(e.get("bullets"))) if t]))
    edu = [Education(id=f"edu_{i}", school=_s(x.get("school")), degree=_s(x.get("degree")), start=_s(x.get("start")),
                     end=_s(x.get("end")), location=_s(x.get("location"))) for i, x in enumerate(_l(d.get("education")))]
    extras = [Bullet(id=f"extra_{i}", text=_s(t)) for i, t in enumerate(_l(d.get("extras"))) if t]
    skills = {_s(k): [_s(x) for x in _l(v)] for k, v in (d.get("skills") or {}).items()}
    return Profile(name=_s(d.get("name")), email=_s(d.get("email")), phone=_s(d.get("phone")),
                   location=_s(d.get("location")), links=[_s(x) for x in _l(d.get("links"))],
                   summary=_s(d.get("summary")), skills=skills, entries=entries, education=edu, extras=extras)


def heuristic_profile(text: str) -> Profile:
    """No-LLM fallback so onboarding never blocks: grabs name + email; the user edits the rest in the UI."""
    m = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text)
    name = next((l.strip() for l in text.splitlines() if l.strip()), "")
    return Profile(name=name, email=m.group(0) if m else "", extras=[Bullet(id="raw_0", text=text[:3000])])
