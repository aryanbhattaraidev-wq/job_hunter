"""Approval gate: approval is bound to a hash of exactly what will be sent. Any change invalidates it."""
from __future__ import annotations
import hashlib, json
from pathlib import Path
from .. import db


def content_hash(app: dict) -> str:
    h = hashlib.sha256()
    for p in (app.get("cv_pdf"), app.get("cover_pdf")):
        h.update(Path(p).read_bytes() if p and Path(p).exists() else b"-")
    h.update((app.get("cover_text") or "").encode())
    h.update((app.get("snapshot_json") or "").encode())
    return h.hexdigest()


def get(c, app_id: int) -> dict:
    r = c.execute("SELECT * FROM applications WHERE id=?", (app_id,)).fetchone()
    if not r:
        raise KeyError(f"no application {app_id}")
    return dict(r)


def approve(app_id: int) -> str:
    c = db.conn()
    app = get(c, app_id)
    if app["approval_status"] == "submitted":
        raise ValueError("already submitted")
    h = content_hash(app)
    c.execute("UPDATE applications SET approval_status='approved', approved_hash=?, approved_at=? WHERE id=?", (h, db.now(), app_id))
    db.log(c, app["job_id"], "approved", {"application": app_id, "hash": h[:12]})
    c.commit()
    return h


def reject(app_id: int) -> None:
    c = db.conn()
    c.execute("UPDATE applications SET approval_status='rejected' WHERE id=?", (app_id,))
    c.commit()


def assert_approved(app: dict) -> None:
    """Raise unless the application is approved AND unchanged since approval."""
    if app["approval_status"] != "approved":
        raise PermissionError(f"application {app['id']} is '{app['approval_status']}', not approved")
    if content_hash(app) != app["approved_hash"]:
        raise PermissionError("application changed after approval; review and approve again")
