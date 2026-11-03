"""Generic, label-driven form filler for Greenhouse / Lever / Ashby style single-page application forms.

It NEVER submits (there is deliberately no submit code in this file; see submit.py). It fills what it can ground in your
profile, flags everything else for you, and never answers sensitive questions (EEO, visa, salary...) on its own.
"""
from __future__ import annotations
import re
from pathlib import Path
from ..config import DATA
from ..profile import Profile

SENSITIVE = re.compile(r"gender|race|ethnic|veteran|disabilit|salary|compensation|sponsor|authori[sz]ed|visa|pronoun|hispanic|citizen|"
                       r"criminal|convicted|date of birth|\bage\b|religio|sexual|expected pay|notice period|relocat", re.I)
FIELD_SELECTOR = "input:not([type=hidden]):not([type=file]):not([type=checkbox]):not([type=radio]):not([type=submit]), textarea, select"

ATS_HOSTS = {"greenhouse": ("greenhouse.io",), "lever": ("lever.co",), "ashby": ("ashbyhq.com",)}


def detect_ats(url: str) -> str:
    for name, hosts in ATS_HOSTS.items():
        if any(h in url for h in hosts):
            return name
    return "generic"


def _link(prof: Profile, key: str) -> str:
    for l in prof.links:
        if key in l.lower():
            return l if l.startswith("http") else "https://" + l
    return ""


def value_for(label: str, prof: Profile) -> tuple[str, str] | None:
    """(value, source) for a label, or None. Only contact facts the user put in their own profile."""
    l = label.lower().strip()
    parts = prof.name.split()
    first, last = (parts[0], " ".join(parts[1:])) if parts else ("", "")
    if re.search(r"first name|given name|preferred name", l): return first, "profile.name"
    if re.search(r"last name|family name|surname", l): return last, "profile.name"
    if re.fullmatch(r"(full )?name\*?|your name", l) or l.startswith("full name"): return prof.name, "profile.name"
    if "email" in l: return prof.email, "profile.email"
    if re.search(r"phone|mobile", l): return prof.phone, "profile.phone"
    if "linkedin" in l: return _link(prof, "linkedin"), "profile.links"
    if "github" in l: return _link(prof, "github"), "profile.links"
    if re.search(r"website|portfolio|personal site|url", l):
        site = next((x for x in prof.links if "linkedin" not in x.lower() and "github" not in x.lower()), "")
        return (site if site.startswith("http") or not site else "https://" + site), "profile.links"
    if re.search(r"current location|city|where are you (located|based)|^location", l): return prof.location, "profile.location"
    return None


def read_label(el) -> str:
    js = """e => {
      const id = e.id; let t = '';
      if (id) { const l = document.querySelector('label[for="' + CSS.escape(id) + '"]'); if (l) t = l.innerText; }
      if (!t) { const l = e.closest('label'); if (l) t = l.innerText; }
      if (!t) t = e.getAttribute('aria-label') || '';
      if (!t) { const lb = e.getAttribute('aria-labelledby'); if (lb) { const n = document.getElementById(lb); if (n) t = n.innerText; } }
      if (!t) { const f = e.closest('.field, .application-question, [class*=field], [class*=question]'); if (f) { const l = f.querySelector('label, legend'); if (l) t = l.innerText; } }
      if (!t) t = e.placeholder || e.name || '';
      return t.replace(/\\s+/g, ' ').trim();
    }"""
    return el.evaluate(js)


def prefill(page, prof: Profile, cv_pdf: str | None, cover_pdf: str | None, cover_text: str = "",
            drafter=None) -> dict:
    """Fill the form on `page`. Returns {filled:[...], needs_user:[...]} (labels + short value previews)."""
    filled, needs = [], []
    for el in page.query_selector_all(FIELD_SELECTOR):
        try:
            if not el.is_visible() or not el.is_editable():
                continue
            label = read_label(el)
            if not label:
                continue
            required = bool(el.get_attribute("required") is not None or el.get_attribute("aria-required") == "true" or label.endswith("*"))
            tag = el.evaluate("e => e.tagName.toLowerCase()")
            if SENSITIVE.search(label):
                needs.append({"label": label, "reason": "sensitive: answer yourself", "required": required})
                continue
            if tag == "textarea":   # any free-text question: cover letter, 'why us', anything else
                if re.search(r"cover letter|additional information", label, re.I) and cover_text:
                    el.fill(cover_text); filled.append({"label": label, "value": cover_text[:60] + "…", "source": "cover_letter"})
                    continue
                draft = drafter(label) if drafter else None
                if draft:
                    el.fill(draft); filled.append({"label": label, "value": draft[:60] + "…", "full": draft, "source": "LLM draft (verified vs profile): REVIEW"})
                else:
                    needs.append({"label": label, "reason": "free-text: write or review", "required": required})
                continue
            hit = value_for(label, prof)
            if hit and hit[0]:
                el.fill(hit[0]); filled.append({"label": label, "value": hit[0], "source": hit[1]})
            elif required:
                needs.append({"label": label, "reason": "no matching fact in profile", "required": True})
        except Exception as e:  # one weird widget must not abort the whole form
            needs.append({"label": "(unreadable field)", "reason": str(e)[:80], "required": False})
    # radio / checkbox questions are never auto-answered: always hand them to the human
    seen_groups = set()
    for ch in page.query_selector_all("input[type=radio], input[type=checkbox]"):
        try:
            q = ch.evaluate("""e => {
                const nl = String.fromCharCode(10);
                const same = e.name ? Array.from(document.querySelectorAll('input[name="' + CSS.escape(e.name) + '"]')) : [e];
                let c = e.parentElement;
                if (same.length > 1) { while (c && c.tagName !== 'BODY' && !same.every(x => c.contains(x))) c = c.parentElement; }
                else { c = e.closest('fieldset, [role=group]') || e.parentElement; }
                const lines = ((c && c.innerText) || '').split(nl).map(x => x.trim()).filter(Boolean);
                const opts = same.map(x => ((x.closest('label') || {}).innerText || '').trim());
                return lines.find(x => !opts.includes(x)) || lines[0] || e.name || '';
            }""")
            key = (ch.get_attribute("name") or "") + "|" + q
            if not q or key in seen_groups or not ch.is_visible():
                continue
            seen_groups.add(key)
            needs.append({"label": q[:140], "reason": "choice question: answer yourself" + (" (sensitive)" if SENSITIVE.search(q) else ""),
                          "required": q.rstrip().endswith("*")})
        except Exception:
            pass
    for fi in page.query_selector_all("input[type=file]"):
        try:
            label = (read_label(fi) or fi.get_attribute("name") or "").lower()
            ctx = fi.evaluate("e => (e.closest('div, fieldset, section')||document.body).innerText.slice(0,200)").lower()
            kind = "cover" if "cover" in label + ctx else "cv"
            path = cover_pdf if kind == "cover" else cv_pdf
            if path and Path(path).exists():
                fi.set_input_files(path); filled.append({"label": label or kind, "value": Path(path).name, "source": kind})
            elif kind == "cv":
                needs.append({"label": label or "resume upload", "reason": "no CV PDF available (compile it first)", "required": True})
        except Exception as e:
            needs.append({"label": "(file input)", "reason": str(e)[:80], "required": False})
    return {"filled": filled, "needs_user": needs}


def open_browser(playwright, headless: bool = False):
    """Persistent Edge profile so logins/cookies survive; no browser download needed on Windows."""
    return playwright.chromium.launch_persistent_context(str(DATA / "browser_profile"), channel="msedge", headless=headless,
                                                         viewport={"width": 1280, "height": 1000})


def goto_form(page, url: str) -> None:
    """Navigate to the application form (shared by prepare and submit so both see the same page)."""
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(2500)
    if not page.query_selector("input[type=email], input[name=email]"):
        link = page.query_selector("a:has-text('Apply'), button:has-text('Apply for this job'), button:has-text('Apply Now')")
        if link:
            try:
                link.click()
                page.wait_for_timeout(2500)
            except Exception:
                pass
