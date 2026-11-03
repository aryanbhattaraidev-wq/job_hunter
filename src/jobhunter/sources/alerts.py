"""LinkedIn / Indeed / Glassdoor via their job-alert EMAILS (no scraping of the sites themselves).

You create alerts on those sites; they email you; we read those emails with the Gmail API (read-only, your own mailbox)
and turn each job link into a job. We then try ONE polite fetch of the public posting to get its description
(JSON-LD JobPosting); if the site blocks it, the job is kept with just the title/company from the email.
"""
from __future__ import annotations
import json, re
import httpx
from selectolax.lexbor import LexborHTMLParser as HTMLParser
from . import UA, strip_html, REMOTE_WORDS

JOB_LINK = re.compile(r"(linkedin\.com/(comm/)?jobs/view|indeed\.[a-z.]+/(rc/clk|viewjob|pagead)|glassdoor\.[a-z.]+/(job-listing|partner/jobListing))", re.I)
NOISE = re.compile(r"unsubscribe|manage|view all|see all|settings|help|privacy|learn more|apply now|^\W*$", re.I)


def parse_alert_html(html: str, sender: str = "") -> list[dict]:
    """Extract (title, company, location, url) tuples from the typical alert-email layout."""
    tree = HTMLParser(html)
    out, seen = [], set()
    for a in tree.css("a"):
        href = a.attributes.get("href") or ""
        if not JOB_LINK.search(href):
            continue
        title = " ".join(a.text().split())
        if not title or NOISE.search(title) or len(title) < 4:
            continue
        key = href.split("?")[0]
        if key in seen:
            continue
        seen.add(key)
        # company / location usually sit in the next text blocks of the same table cell
        company = location = ""
        parent = a.parent
        for _ in range(3):
            if parent is None:
                break
            lines = [" ".join(t.split()) for t in parent.text(separator="\n").split("\n") if t.strip()]
            lines = [l for l in lines if l != title and not NOISE.search(l)]
            if lines:
                company = lines[0][:80]
                location = lines[1][:80] if len(lines) > 1 else ""
                break
            parent = parent.parent
        src = "linkedin" if "linkedin" in href else "indeed" if "indeed" in href else "glassdoor"
        out.append(dict(source=f"alert_{src}", external_id=key, title=title, company=company, location=location,
                        remote=bool(REMOTE_WORDS.search(location + title)), url=href, description=""))
    return out


def fetch_description(url: str) -> str:
    """One gentle attempt; blocked pages (login walls, 999/403) simply yield ''."""
    try:
        r = httpx.get(url, headers=UA, timeout=15, follow_redirects=True)
        if r.status_code != 200:
            return ""
        tree = HTMLParser(r.text)
        for s in tree.css('script[type="application/ld+json"]'):
            try:
                data = json.loads(s.text())
            except ValueError:
                continue
            for d in (data if isinstance(data, list) else [data]):
                if isinstance(d, dict) and d.get("@type") == "JobPosting":
                    return strip_html(d.get("description", ""))
    except Exception:
        pass
    return ""


def email_alerts(cfg):
    from ..notify.gmail import read_alert_html
    for sender, html in read_alert_html():
        for j in parse_alert_html(html, sender):
            j["description"] = fetch_description(j["url"])
            yield j
