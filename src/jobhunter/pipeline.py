"""discover -> prefilter (free rules) -> score (deterministic, explainable). No LLM needed."""
from __future__ import annotations
import json, re
from . import db, sources
from .config import Config, Preferences, load_config
from .profile import Profile, load_profile

ROLE_SYNONYMS = {
    "ai engineer": ["ai engineer", "artificial intelligence", "llm", "generative ai", "genai", "agent", "applied ai", "ai developer", "ai/ml"],
    "machine learning engineer": ["machine learning", "ml engineer", "mlops", "deep learning", "nlp", "computer vision", "data scientist"],
}
SENIORITY_PATTERNS = {
    "internship": r"\bintern(ship)?\b",
    "trainee": r"\b(trainee|apprentice|graduate|new grad|entry[- ]level|early career)\b",
    "junior": r"\b(junior|jr\.?|associate|entry)\b",
    "senior": r"\b(senior|sr\.?|staff|principal|head of|director|vp)\b",
    "lead": r"\b(lead|manager|architect)\b",
}
UNPAID = re.compile(r"\bunpaid\b|volunteer|no (stipend|compensation)|without pay", re.I)
# Remote jobs restricted to regions that exclude Nepal
GEO_RESTRICT = re.compile(
    r"(us|u\.s\.|usa|united states|uk|canada|eu|europe|emea|latam|north america|germany|india)[- ]?(only|based|residents|citizens)"
    r"|must (be|reside|live) (located )?(in|within) (the )?(us|u\.s\.|united states|uk|eu|europe|canada)"
    r"|authori[sz]ed to work in (the )?(us|u\.s\.|united states|uk|canada)|no sponsorship|us work authorization|security clearance|u\.s\. citizen|us citizen|citizenship required|clearance required", re.I)
WORLDWIDE = re.compile(r"worldwide|anywhere|global|any location|all countries|asia|apac|nepal|south asia", re.I)


def seniority_of(title: str, desc: str) -> str:
    t = title.lower()
    for lvl in ("internship", "trainee", "junior", "senior", "lead"):
        if re.search(SENIORITY_PATTERNS[lvl], t):
            return lvl
    m = re.search(r"(\d+)\+?\s*(?:-\s*\d+\s*)?years", desc[:2500].lower())
    if m:
        y = int(m.group(1))
        return "junior" if y <= 1 else "mid" if y <= 4 else "senior"
    return "mid"


def role_hits(title: str, desc: str, roles: list[str]) -> tuple[int, int]:
    """(title_hits, desc_hits) against targets + synonyms."""
    terms = set()
    for r in roles:
        r = r.lower()
        terms.add(r)
        terms.update(ROLE_SYNONYMS.get(r, []))
    t, d = title.lower(), desc.lower()[:4000]
    return sum(x in t for x in terms), sum(x in d for x in terms)


REGIONS = re.compile(r"\b(us|usa|u\.s\.|united states|uk|united kingdom|canada|europe|eu|emea|latam|north america|india|germany|france|"
                     r"brazil|mexico|australia|japan|singapore|korea|ireland|spain|poland|netherlands|israel|uae|china|taiwan)\b", re.I)


def location_ok(j: dict, p: Preferences) -> tuple[bool, str]:
    loc = (j.get("location") or "").lower()
    for l in p.locations:
        if l.lower() in f"{loc} {j['title'].lower()}" or l.lower() in j.get("description", "")[:600].lower():
            return True, f"in {l}"
    if not p.remote_worldwide:
        return False, "location"
    loc_clean = re.sub(r"remote[- ]friendly", "", loc)
    is_remote = bool(j.get("remote")) or bool(sources.REMOTE_WORDS.search(loc_clean + " " + j["title"]))
    if not is_remote:
        return False, "location"
    if WORLDWIDE.search(loc):
        return True, "remote"
    if REGIONS.search(loc):
        return False, "remote but region-restricted"
    if loc.strip() and not sources.REMOTE_WORDS.search(loc_clean):
        return False, "remote flag but on-site location"      # e.g. "Tokyo" / "San Francisco"
    if GEO_RESTRICT.search(f"{loc} {j.get('description', '')[:2500]}"):
        return False, "remote but region-restricted"
    return True, "remote"


def prefilter(j: dict, p: Preferences) -> str | None:
    """Return a reject reason or None. Cheap rules only."""
    title = j["title"].lower()
    if title.startswith("http") or len(title) < 4 or title in ("multiple roles", "various roles"):
        return "unusable title"
    if any(k.lower() in title for k in p.exclude_keywords):
        return "excluded keyword"
    th, dh = role_hits(j["title"], j.get("description", ""), p.target_roles)
    if th == 0 and dh < 3:
        return "not a target role"
    sen = seniority_of(j["title"], j.get("description", ""))
    if sen not in p.seniorities:
        return f"seniority {sen}"
    if p.require_paid and UNPAID.search(f"{j['title']} {j.get('description', '')[:1500]}"):
        return "unpaid"
    ok, why = location_ok(j, p)
    if not ok:
        return why
    return None


def score(j: dict, prof: Profile | None, p: Preferences) -> tuple[float, dict]:
    th, dh = role_hits(j["title"], j.get("description", ""), p.target_roles)
    role = min(1.0, 0.6 * min(th, 1) + 0.4 * min(dh / 4, 1))
    desc = j.get("description", "").lower()
    skills = sorted(prof.skill_set()) if prof else []
    matched = [s for s in skills if len(s) > 1 and re.search(rf"(?<![a-z0-9]){re.escape(s)}(?![a-z0-9])", desc)]
    skill = min(1.0, len(matched) / 6) if skills else 0.5
    sen = seniority_of(j["title"], j.get("description", ""))
    sen_score = 1.0 if sen in ("trainee", "junior") else 0.8 if sen in ("internship", "mid") else 0.3
    boost = [k for k in p.include_keywords if k.lower() in desc or k.lower() in j["title"].lower()]
    kw = min(1.0, len(boost) / 2) if p.include_keywords else 0.5
    loc_ok, loc_why = location_ok(j, p)
    loc = 1.0 if loc_why.startswith("in ") else 0.8 if loc_ok else 0
    total = 100 * (0.30 * role + 0.35 * skill + 0.15 * sen_score + 0.10 * kw + 0.10 * loc)
    return round(total, 1), dict(role=round(role, 2), skills=round(skill, 2), seniority=sen, matched_skills=matched,
                                 boosted=boost, location=loc_why, salary=j.get("salary", ""))


def run_discovery(cfg: Config | None = None, progress=lambda *_: None) -> dict:
    cfg = cfg or load_config()
    prof = load_profile()
    c = db.conn()
    stats = {"seen": 0, "new": 0, "kept": 0, "rejected": 0, "errors": {}}
    for name, item in sources.discover(cfg.sources):
        if isinstance(item, Exception):
            stats["errors"][name] = str(item)[:120]
            progress("error", name, item)
            continue
        stats["seen"] += 1
        if not db.upsert_job(c, item):
            continue
        stats["new"] += 1
        jid = c.execute("SELECT id FROM jobs WHERE fingerprint=?", (db.fingerprint(item["company"], item["title"], item.get("location", "")),)).fetchone()["id"]
        why = prefilter(item, cfg.preferences)
        if why:
            c.execute("UPDATE jobs SET status='rejected', reject_reason=? WHERE id=?", (why, jid))
            stats["rejected"] += 1
        else:
            s, detail = score(item, prof, cfg.preferences)
            c.execute("UPDATE jobs SET status='scored', score=?, score_json=? WHERE id=?", (s, json.dumps(detail), jid))
            stats["kept"] += 1
    c.commit()
    return stats


def top_jobs(min_score: float = 0, limit: int = 50, status: str = "scored"):
    c = db.conn()
    return c.execute("SELECT * FROM jobs WHERE status IN (?, 'notified', 'tailored') AND score>=? ORDER BY score DESC LIMIT ?",
                     (status, min_score, limit)).fetchall()
