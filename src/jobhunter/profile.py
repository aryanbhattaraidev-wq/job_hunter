"""Master profile: every claim has a stable ID so tailoring can be verified against it."""
from __future__ import annotations
import re
from pydantic import BaseModel, Field
from .config import PROFILE_PATH, DATA


class Bullet(BaseModel):
    id: str
    text: str
    skills: list[str] = []
    verified: bool = True


class Entry(BaseModel):          # experience / project
    id: str
    kind: str = "experience"     # experience | project
    org: str = ""                # company or project name
    title: str = ""
    start: str = ""
    end: str = ""
    location: str = ""
    tech: list[str] = []
    bullets: list[Bullet] = []


class Education(BaseModel):
    id: str
    school: str
    degree: str = ""
    start: str = ""
    end: str = ""
    location: str = ""


class Profile(BaseModel):
    name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    links: list[str] = []
    summary: str = ""
    skills: dict[str, list[str]] = Field(default_factory=dict)   # category -> skills
    entries: list[Entry] = []
    education: list[Education] = []
    extras: list[Bullet] = []    # publications, certifications, etc.

    def all_bullets(self) -> dict[str, Bullet]:
        out = {b.id: b for e in self.entries for b in e.bullets}
        out.update({b.id: b for b in self.extras})
        return out

    def skill_set(self) -> set[str]:
        s = {x.lower() for v in self.skills.values() for x in v}
        for e in self.entries:
            s |= {t.lower() for t in e.tech}
        return s

    def text_blob(self) -> str:
        parts = [self.summary, " ".join(self.skill_set())]
        parts += [f"{e.title} {e.org} {' '.join(e.tech)}" for e in self.entries]
        parts += [b.text for b in self.all_bullets().values()]
        return " ".join(parts).lower()


def load_profile() -> Profile | None:
    if PROFILE_PATH.exists():
        return Profile.model_validate_json(PROFILE_PATH.read_text(encoding="utf-8"))
    return None


def save_profile(p: Profile) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(p.model_dump_json(indent=2), encoding="utf-8")


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:24] or "x"
