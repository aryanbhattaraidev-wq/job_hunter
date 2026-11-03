from __future__ import annotations
import sqlite3, json, hashlib, re
from datetime import datetime, timezone
from .config import DB_PATH, DATA

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs(
  id INTEGER PRIMARY KEY, fingerprint TEXT UNIQUE, source TEXT, external_id TEXT,
  title TEXT, company TEXT, location TEXT, remote INTEGER DEFAULT 0, url TEXT,
  description TEXT, salary TEXT, posted_at TEXT, first_seen TEXT, last_seen TEXT,
  status TEXT DEFAULT 'new',
  score REAL, score_json TEXT, reject_reason TEXT);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE TABLE IF NOT EXISTS documents(
  id INTEGER PRIMARY KEY, job_id INTEGER, kind TEXT, tex_path TEXT, pdf_path TEXT, report_json TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS applications(
  id INTEGER PRIMARY KEY, job_id INTEGER, cv_pdf TEXT, cover_pdf TEXT, cover_text TEXT,
  snapshot_json TEXT, needs_user_json TEXT, screenshot TEXT,
  approval_status TEXT DEFAULT 'pending',   -- pending | approved | rejected | submitted
  approved_hash TEXT, approved_at TEXT, submitted_at TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, ts TEXT, job_id INTEGER, type TEXT, payload TEXT);
"""
# status: new | rejected | scored | notified | tailored | applied | closed


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def conn() -> sqlite3.Connection:
    DATA.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.executescript(SCHEMA)
    return c


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def fingerprint(company: str, title: str, location: str) -> str:
    return hashlib.sha1(f"{norm(company)}|{norm(title)}|{norm(location)}".encode()).hexdigest()


def upsert_job(c: sqlite3.Connection, j: dict) -> bool:
    """Insert if new; refresh last_seen otherwise. Returns True when new."""
    fp = fingerprint(j["company"], j["title"], j.get("location", ""))
    row = c.execute("SELECT id FROM jobs WHERE fingerprint=?", (fp,)).fetchone()
    if row:
        c.execute("UPDATE jobs SET last_seen=? WHERE id=?", (now(), row["id"]))
        return False
    c.execute("""INSERT INTO jobs(fingerprint,source,external_id,title,company,location,remote,url,
                 description,salary,posted_at,first_seen,last_seen) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (fp, j["source"], str(j.get("external_id", "")), j["title"], j["company"], j.get("location", ""),
               int(bool(j.get("remote"))), j["url"], j.get("description", ""), j.get("salary", ""),
               j.get("posted_at", ""), now(), now()))
    return True


def log(c, job_id, type_, payload=None):
    c.execute("INSERT INTO events(ts,job_id,type,payload) VALUES(?,?,?,?)", (now(), job_id, type_, json.dumps(payload or {})))
