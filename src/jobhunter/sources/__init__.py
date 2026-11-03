"""Free, public job sources. Each adapter returns normalized dicts; failures never crash a run.

LinkedIn/Indeed/Glassdoor are intentionally NOT scraped (ToS + account-ban risk). Their job-alert
emails are ingested via the Gmail API instead (see notify/gmail.py -> read_alert_emails).
"""
from __future__ import annotations
import html, re
import httpx
import feedparser
try:  # use the OS certificate store (fixes corporate/AV-intercepted TLS on Windows)
    import truststore; truststore.inject_into_ssl()
except Exception:
    pass

UA = {"User-Agent": "jobhunter/0.1 (personal job search; +local)"}
REMOTE_WORDS = re.compile(r"remote|anywhere|worldwide|work from home|distributed", re.I)


def strip_html(s: str) -> str:
    s = html.unescape(s or "")
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()


def _get(url: str, **kw):
    r = httpx.get(url, headers=UA, timeout=30, follow_redirects=True, **kw)
    r.raise_for_status()
    return r


def remoteok(cfg):
    for j in _get("https://remoteok.com/api").json()[1:]:
        yield dict(source="remoteok", external_id=j.get("id"), title=j.get("position", ""), company=j.get("company", ""),
                   location=j.get("location") or "Remote", remote=True, url=j.get("url") or j.get("apply_url", ""),
                   description=strip_html(j.get("description", "")), posted_at=j.get("date", ""),
                   salary=f"{j['salary_min']}-{j['salary_max']}" if j.get("salary_min") else "")


def remotive(cfg):
    for j in _get("https://remotive.com/api/remote-jobs", params={"search": "ai"}).json().get("jobs", []):
        yield dict(source="remotive", external_id=j["id"], title=j["title"], company=j["company_name"],
                   location=j.get("candidate_required_location", "Remote"), remote=True, url=j["url"],
                   description=strip_html(j.get("description", "")), posted_at=j.get("publication_date", ""),
                   salary=j.get("salary", ""))


def arbeitnow(cfg):
    for j in _get("https://www.arbeitnow.com/api/job-board-api").json().get("data", []):
        yield dict(source="arbeitnow", external_id=j["slug"], title=j["title"], company=j["company_name"],
                   location=j.get("location", ""), remote=bool(j.get("remote")), url=j["url"],
                   description=strip_html(j.get("description", "")), posted_at=str(j.get("created_at", "")))


def weworkremotely(cfg):
    for feed in ("https://weworkremotely.com/categories/remote-programming-jobs.rss",
                 "https://weworkremotely.com/categories/remote-data-jobs.rss"):
        for e in feedparser.parse(feed).entries:
            company, _, title = e.title.partition(": ")
            yield dict(source="weworkremotely", external_id=e.get("id", e.link), title=title or e.title,
                       company=company if title else "", location=e.get("region", "Remote"), remote=True,
                       url=e.link, description=strip_html(e.get("summary", "")), posted_at=e.get("published", ""))


def hn(cfg):
    """Latest 'Ask HN: Who is hiring?' thread; one job per top-level comment (first line = headline)."""
    q = _get("https://hn.algolia.com/api/v1/search_by_date", params={"query": "Ask HN: Who is hiring", "tags": "story,author_whoishiring", "hitsPerPage": 1}).json()
    if not q["hits"]:
        return
    sid = q["hits"][0]["objectID"]
    for c in _get(f"https://hn.algolia.com/api/v1/items/{sid}").json().get("children", []):
        text = strip_html(c.get("text") or "")
        if len(text) < 40:
            continue
        head = text.split("|")
        company = head[0].strip()[:60]
        title = head[1].strip()[:100] if len(head) > 1 else text[:80]
        yield dict(source="hn", external_id=c["id"], title=title, company=company,
                   location="Remote" if REMOTE_WORDS.search(text[:300]) else "", remote=bool(REMOTE_WORDS.search(text[:300])),
                   url=f"https://news.ycombinator.com/item?id={c['id']}", description=text, posted_at=c.get("created_at", ""))


def _ats(name, slugs, fetch):
    for slug in slugs:
        try:
            yield from fetch(slug)
        except Exception:  # bad slug / ATS hiccup: skip, never abort the run
            continue


def greenhouse(cfg):
    def f(slug):
        for j in _get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", params={"content": "true"}).json().get("jobs", []):
            loc = (j.get("location") or {}).get("name", "")
            yield dict(source="greenhouse", external_id=j["id"], title=j["title"], company=slug, location=loc,
                       remote=bool(REMOTE_WORDS.search(loc)), url=j["absolute_url"],
                       description=strip_html(j.get("content", "")), posted_at=j.get("updated_at", ""))
    yield from _ats("greenhouse", cfg.watchlist.get("greenhouse", []), f)


def lever(cfg):
    def f(slug):
        for j in _get(f"https://api.lever.co/v0/postings/{slug}", params={"mode": "json"}).json():
            cat = j.get("categories", {})
            loc = cat.get("location", "") or ""
            yield dict(source="lever", external_id=j["id"], title=j["text"], company=slug, location=loc,
                       remote=bool(REMOTE_WORDS.search(loc + (j.get("workplaceType") or ""))), url=j["hostedUrl"],
                       description=j.get("descriptionPlain", ""), posted_at=str(j.get("createdAt", "")))
    yield from _ats("lever", cfg.watchlist.get("lever", []), f)


def ashby(cfg):
    def f(slug):
        for j in _get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}").json().get("jobs", []):
            loc = j.get("location", "") or ""
            yield dict(source="ashby", external_id=j["id"], title=j["title"], company=slug, location=loc,
                       remote=(j.get("workplaceType") == "Remote") or bool(REMOTE_WORDS.search(loc)), url=j["jobUrl"],
                       description=j.get("descriptionPlain", ""), posted_at=j.get("publishedAt", ""))
    yield from _ats("ashby", cfg.watchlist.get("ashby", []), f)


def rss_extra(cfg):
    for url in cfg.extra_rss:
        for e in feedparser.parse(url).entries:
            yield dict(source="rss", external_id=e.get("id", e.link), title=e.title, company=e.get("author", ""),
                       location=e.get("location", ""), remote=bool(REMOTE_WORDS.search(e.title + e.get("summary", ""))),
                       url=e.link, description=strip_html(e.get("summary", "")), posted_at=e.get("published", ""))


def email_alerts(cfg):
    from .alerts import email_alerts as _f
    yield from _f(cfg)


REGISTRY = {"email_alerts": email_alerts, "remoteok": remoteok, "remotive": remotive, "arbeitnow": arbeitnow, "weworkremotely": weworkremotely,
            "hn": hn, "greenhouse": greenhouse, "lever": lever, "ashby": ashby, "rss": rss_extra}


def discover(sources_cfg):
    """Yield (source_name, job_dict | Exception) so callers can report per-source health."""
    for name in sources_cfg.enabled + (["rss"] if sources_cfg.extra_rss else []):
        fn = REGISTRY.get(name)
        if not fn:
            continue
        try:
            for j in fn(sources_cfg):
                if j.get("title") and j.get("url"):
                    yield name, j
        except Exception as e:
            yield name, e
