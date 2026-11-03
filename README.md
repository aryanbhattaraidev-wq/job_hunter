# Job Hunter

Free, local-first job hunting + CV tailoring that works with **anyone's resume**.
**Nothing is ever submitted without your explicit approval.**

## Quick start
```
python -m venv .venv && .venv\Scripts\activate
pip install -e .
jobhunter ui          # guided setup: resume -> preferences -> sources -> AI -> notifications -> jobs -> applications
```

## Daily flow
| Command | What it does |
|---|---|
| `jobhunter run` | discover -> filter/score -> AI re-rank -> Telegram/email digest (safe to schedule; can never submit) |
| `jobhunter jobs` / `show <id>` | ranked matches with the AI's one-line verdict |
| `jobhunter tailor <id>` | tailored LaTeX/PDF CV (real facts only) + list of skill gaps |
| `jobhunter cover <id>` | cover letter, every claim cites a profile fact; numbers/tech are checked in code |
| `jobhunter prepare <id>` | tailors, writes the letter, **pre-fills the real application form**, screenshots it, queues it |
| `jobhunter review <app>` / `approve` | you inspect everything that will be sent, then approve |
| `jobhunter submit <app>` | re-checks the approval hash, re-fills the form, asks one last time, then clicks submit |
| `jobhunter probe` | finds which company boards (Greenhouse/Lever/Ashby) really exist and adds them |
| `jobhunter schedule 08:00` | Windows daily task for `run` |

## Safety design
- **No fabrication:** CVs only select/reorder profile facts; cover letters must cite fact IDs and pass number/technology checks; failing drafts are left for you.
- **Approval gate:** approval is bound to a hash of the CV, letter and every filled field. Any change invalidates it.
- **One submit path:** only `apply/submit.py` can click submit (a test enforces it). The scheduler path never imports it.
- **Never auto-answered:** EEO, visa/work-authorization, salary, clearance, any radio/checkbox question. They are listed for you.
- Job postings are untrusted text (prompt-injection guarded).

## Everything is free (paid models optional)
- **AI:** Gemini free tier by default (auto-falls back across Gemini models). Optional OpenRouter key for the "smart" model used for cover letters, capped by `smart_daily_cap` calls/day to protect your balance.
- **Telegram:** @BotFather -> /newbot -> token in the UI -> message your bot -> "Detect chat id".
- **Gmail (optional):** free Google Cloud OAuth "Desktop app" client saved as `data/credentials.json`. Used to send digests and to read LinkedIn/Indeed/Glassdoor **alert emails** (enable the `email_alerts` source).
- **PDF:** Tectonic (`tools/tectonic.exe`) or MiKTeX. Needs internet access to CTAN-style bundle hosts; some office networks block this. The `.tex` always works (Overleaf).
- **Form filling** uses your installed Microsoft Edge via Playwright (no browser download).

## Sources
RemoteOK, Remotive, Arbeitnow, WeWorkRemotely, HN "Who is hiring", ~100 verified company boards (Greenhouse/Lever/Ashby), custom RSS, and alert emails.
LinkedIn/Indeed/Glassdoor are deliberately **not scraped** (ToS / account bans).

Secrets live in `.env` (git-ignored). Data in `data/`. Tests: `pytest`.
