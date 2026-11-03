"""Gmail API (free quota): send digests, and READ LinkedIn/Indeed/Glassdoor job-alert emails.

One-time setup: create an OAuth 'Desktop app' client in Google Cloud Console (free), enable the Gmail API,
download it as data/credentials.json. First call opens a browser for consent and stores data/token.json.
"""
from __future__ import annotations
import base64, re
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from ..config import DATA

SCOPES = ["https://www.googleapis.com/auth/gmail.send", "https://www.googleapis.com/auth/gmail.readonly"]
ALERT_SENDERS = ["jobalerts-noreply@linkedin.com", "jobs-noreply@linkedin.com", "alert@indeed.com", "noreply@glassdoor.com", "jobalert@glassdoor.com"]


def _service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    tok, cred = DATA / "token.json", DATA / "credentials.json"
    creds = Credentials.from_authorized_user_file(str(tok), SCOPES) if tok.exists() else None
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not cred.exists():
                raise RuntimeError(f"Put your Google OAuth client file at {cred} (see README: Gmail setup)")
            creds = InstalledAppFlow.from_client_secrets_file(str(cred), SCOPES).run_local_server(port=0)
        tok.write_text(creds.to_json())
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def send_email(to: str, subject: str, text: str, html_body: str | None = None) -> None:
    msg = MIMEMultipart("alternative")
    msg["To"], msg["Subject"] = to, subject
    msg.attach(MIMEText(text, "plain"))
    if html_body:
        msg.attach(MIMEText(html_body, "html"))
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    _service().users().messages().send(userId="me", body={"raw": raw}).execute()


def read_alert_html(max_messages: int = 25):
    """Yield (sender, html_body) for recent LinkedIn/Indeed/Glassdoor alert emails (read-only)."""
    svc = _service()
    q = "(" + " OR ".join(f"from:{s}" for s in ALERT_SENDERS) + ") newer_than:3d"
    for m in svc.users().messages().list(userId="me", q=q, maxResults=max_messages).execute().get("messages", []):
        full = svc.users().messages().get(userId="me", id=m["id"], format="full").execute()
        sender = next((h["value"] for h in full["payload"]["headers"] if h["name"].lower() == "from"), "")
        yield sender, _body(full["payload"])


def _body(payload) -> str:
    out = ""
    if payload.get("body", {}).get("data"):
        out += base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", "ignore")
    for p in payload.get("parts", []) or []:
        out += _body(p)
    return out
