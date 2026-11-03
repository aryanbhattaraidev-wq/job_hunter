from __future__ import annotations
import json, subprocess, sys
from pathlib import Path
import typer
from rich.console import Console
from rich.table import Table
from . import db, pipeline, config as C

app = typer.Typer(help="Free, local-first job hunting + CV tailoring. Nothing is ever submitted without your approval. Start: jobhunter ui")
con = Console()
C.load_dotenv()


def _job(job_id: int) -> dict:
    r = db.conn().execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not r:
        raise typer.BadParameter(f"no job {job_id}")
    return dict(r)


def _profile():
    from .profile import load_profile
    p = load_profile()
    if not p:
        raise typer.BadParameter("No profile yet: run `jobhunter import-resume <file>` or use `jobhunter ui`.")
    return p


@app.command()
def ui():
    """Open the setup & dashboard interface in your browser."""
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(Path(__file__).parent / "ui" / "app.py")])


@app.command("import-resume")
def import_resume(path: Path):
    """Parse a resume (PDF/txt) into your profile (uses the LLM if configured, else a minimal fallback)."""
    from . import resume_import as R, llm
    from .profile import save_profile
    text = R.extract_text(path)
    try:
        prof = R.from_text(text)
    except llm.LLMUnavailable as e:
        con.print(f"[yellow]No LLM available ({e}); using minimal fallback. Edit the profile in the UI.[/]")
        prof = R.heuristic_profile(text)
    save_profile(prof)
    con.print(f"Saved profile for [bold]{prof.name}[/]: {len(prof.entries)} entries, {len(prof.all_bullets())} facts.")


@app.command()
def discover():
    """Fetch jobs from all enabled sources, filter and score them."""
    stats = pipeline.run_discovery(progress=lambda k, n, e: con.print(f"[red]{n} failed:[/] {str(e)[:100]}"))
    con.print(stats)


@app.command()
def rerank(limit: int = 15):
    """Have the AI re-read the top matches and give a realistic fit (catches hidden '5+ years')."""
    from . import ai
    n = ai.rerank_top(limit, progress=lambda k, i, e: con.print(f"[red]job {i}:[/] {str(e)[:100]}"))
    con.print(f"re-ranked {n} jobs")


@app.command()
def jobs(min_score: float = 0, limit: int = 30):
    """List best-scoring jobs."""
    t = Table("id", "score", "title", "company", "where", "ai note", show_lines=False)
    for r in pipeline.top_jobs(min_score, limit):
        d = json.loads(r["score_json"] or "{}")
        t.add_row(str(r["id"]), f"{r['score']:.0f}", r["title"][:44], r["company"][:20], (r["location"] or "remote")[:16], (d.get("llm", {}).get("one_line") or "")[:60])
    con.print(t)


@app.command()
def show(job_id: int):
    """Show a job with its score breakdown, link and description."""
    j = _job(job_id)
    d = json.loads(j["score_json"] or "{}")
    con.print(f"[bold]{j['title']}[/] @ {j['company']} ({j['location']})  score {j['score']}\n{j['url']}\n{json.dumps(d, indent=1)}\n\n{j['description'][:1500]}")


@app.command()
def tailor(job_id: int):
    """Generate a tailored LaTeX/PDF CV for a job (selects real facts only; reports skill gaps)."""
    from .cv import tailor as do_tailor
    out = do_tailor(_profile(), _job(job_id))
    con.print(out)
    if not out["pdf"]:
        con.print("[yellow]PDF not compiled (Tectonic could not download its packages on this network). The .tex is ready; upload it to Overleaf or retry elsewhere.[/]")


@app.command()
def cover(job_id: int):
    """Write a grounded, verified cover letter (paid model within your daily cap, else free)."""
    from . import ai
    j = _job(job_id)
    try:
        brief = ai.company_brief(j)
    except Exception:
        brief = None
    r = ai.cover_letter(_profile(), j, brief)
    con.print(r["text"])
    if r["problems"]:
        con.print(f"[yellow]Unresolved checks: {r['problems']}. Review before using.[/]")
    con.print(f"saved: {r['path']}")


@app.command()
def brief(job_id: int):
    """Company/role brief from the posting text only."""
    from . import ai
    con.print_json(json.dumps(ai.company_brief(_job(job_id))))


@app.command()
def probe():
    """Find which company boards really exist (Greenhouse/Lever/Ashby) and add them to your watchlist."""
    from .sources.probe import probe as do_probe
    found = do_probe()
    cfg = C.load_config()
    for k, v in found.items():
        cfg.sources.watchlist[k] = sorted(set(cfg.sources.watchlist.get(k, [])) | set(v))
    C.save_config(cfg)
    con.print({k: len(v) for k, v in cfg.sources.watchlist.items()})


@app.command()
def prepare(job_id: int, show_browser: bool = typer.Option(False, "--show", help="watch the browser fill the form")):
    """Tailor CV + cover letter and PRE-FILL the real application form. Does NOT submit. Queues it for your approval."""
    from .apply import prepare_application
    r = prepare_application(job_id, headless=not show_browser, progress=con.print)
    con.print(r)
    con.print(f"\nNext: [bold]jobhunter review {r['application_id']}[/] then approve and submit.")


@app.command()
def apps():
    """List prepared applications and their approval status."""
    t = Table("app", "job", "title", "status", "filled", "needs you")
    for r in db.conn().execute("SELECT a.*, j.title, j.company FROM applications a JOIN jobs j ON j.id=a.job_id ORDER BY a.id DESC"):
        snap = json.loads(r["snapshot_json"] or "{}")
        t.add_row(str(r["id"]), str(r["job_id"]), f"{r['title'][:40]} @ {r['company'][:18]}", r["approval_status"], str(len(snap.get("filled", []))), str(len(json.loads(r["needs_user_json"] or "[]"))))
    con.print(t)


@app.command()
def review(app_id: int):
    """Review a prepared application, then approve / reject / skip."""
    from .apply import approval
    a = approval.get(db.conn(), app_id)
    j = _job(a["job_id"])
    snap = json.loads(a["snapshot_json"])
    con.print(f"[bold]{j['title']}[/] @ {j['company']}\n{j['url']}\nCV: {a['cv_pdf'] or '(no PDF yet)'}   screenshot: {a['screenshot']}")
    t = Table("field", "value", "source")
    for f in snap["filled"]:
        t.add_row(f["label"][:50], f["value"][:70], f["source"][:40])
    con.print(t)
    for n in snap["needs_user"]:
        con.print(f"[yellow]needs you:[/] {n['label']}  ({n['reason']})")
    if a["cover_text"]:
        con.print("\n[bold]Cover letter[/]\n" + a["cover_text"])
    choice = typer.prompt("\n[a]pprove / [r]eject / [s]kip", default="s").lower()
    if choice.startswith("a"):
        con.print(f"approved (hash {approval.approve(app_id)[:12]}). Submit with: jobhunter submit {app_id}")
    elif choice.startswith("r"):
        approval.reject(app_id)
        con.print("rejected")


@app.command()
def approve(app_id: int):
    from .apply import approval
    con.print(f"approved (hash {approval.approve(app_id)[:12]})")


@app.command()
def submit(app_id: int):
    """Submit an APPROVED application. Re-checks the approval hash, re-fills the form, and asks one last time."""
    from .apply.submit import submit_application
    r = submit_application(app_id, confirm=lambda s: typer.confirm(f"Submit now?  {s}", default=False))
    con.print(r)


@app.command()
def notify():
    """Send the digest of new matches via the enabled channels."""
    from .notify import notify_all
    con.print(notify_all())


@app.command()
def run():
    """The daily job: discover -> AI re-rank -> notify. Safe to schedule; it can never submit anything."""
    discover()
    try:
        rerank()
    except Exception as e:
        con.print(f"[yellow]re-rank skipped: {e}[/]")
    notify()


@app.command()
def schedule(time: str = "08:00"):
    """Install a daily Windows Task Scheduler entry for `jobhunter run`."""
    exe = Path(sys.executable).with_name("jobhunter.exe")
    subprocess.run(["schtasks", "/Create", "/F", "/SC", "DAILY", "/ST", time, "/TN", "JobHunterDaily", "/TR", f'"{exe}" run'], check=True)
    con.print(f"Scheduled daily at {time}.")


if __name__ == "__main__":
    app()
