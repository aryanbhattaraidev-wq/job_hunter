"""User configuration: the single source of truth filled in by the UI (or edited by hand)."""
from __future__ import annotations
import json, os
from pathlib import Path
from pydantic import BaseModel, Field

ROOT = Path(os.environ.get("JOBHUNTER_HOME", Path(__file__).resolve().parents[2]))
DATA = ROOT / "data"
CONFIG_PATH = DATA / "config.json"
PROFILE_PATH = DATA / "profile.json"
DB_PATH = DATA / "jobhunter.db"
ARTIFACTS = DATA / "artifacts"

SENIORITIES = ["internship", "trainee", "junior", "mid", "senior", "lead"]


class Preferences(BaseModel):
    target_roles: list[str] = ["AI Engineer", "Machine Learning Engineer", "LLM Engineer"]
    seniorities: list[str] = ["trainee", "junior", "mid"]
    include_keywords: list[str] = []          # extra must-ish keywords (boost)
    exclude_keywords: list[str] = []          # drop jobs containing these in title
    locations: list[str] = ["Nepal"]
    remote_worldwide: bool = True
    require_paid: bool = True                 # drop unpaid internships/volunteer
    min_salary_usd_year: int | None = None
    max_age_days: int = 30


class LLMConfig(BaseModel):
    provider: str = "gemini"                  # gemini | groq | openrouter | ollama | anthropic | none
    model: str = ""                           # blank = provider default
    api_key_env: str = ""                     # name of env var holding the key (blank = default for provider)
    smart_provider: str = "openrouter"        # used only for quality-critical writing (cover letters); falls back to the main provider
    smart_model: str = "anthropic/claude-sonnet-5.5"
    smart_daily_cap: int = 20                 # max paid calls per day (protects your OpenRouter balance)


class NotifyConfig(BaseModel):
    telegram_enabled: bool = False
    telegram_chat_id: str = ""                # bot token lives in env TELEGRAM_BOT_TOKEN
    email_enabled: bool = False
    email_to: str = ""
    min_score: int = 60
    digest_max: int = 15


class SourcesConfig(BaseModel):
    enabled: list[str] = ["remoteok", "remotive", "arbeitnow", "weworkremotely", "hn", "greenhouse", "lever", "ashby"]
    watchlist: dict[str, list[str]] = Field(default_factory=lambda: {
        "greenhouse": ["anthropic", "databricks", "scaleai"], "lever": ["mistral"], "ashby": ["openai", "cohere"]})  # ats -> slugs (edit freely; bad slugs are skipped)
    extra_rss: list[str] = []


class Config(BaseModel):
    preferences: Preferences = Preferences()
    llm: LLMConfig = LLMConfig()
    notify: NotifyConfig = NotifyConfig()
    sources: SourcesConfig = SourcesConfig()
    onboarded: bool = False


def load_config() -> Config:
    if CONFIG_PATH.exists():
        return Config.model_validate_json(CONFIG_PATH.read_text(encoding="utf-8"))
    return Config()


def save_config(cfg: Config) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(cfg.model_dump_json(indent=2), encoding="utf-8")


def load_dotenv() -> None:
    """Tiny .env loader (no dependency). Secrets stay in .env, never in config.json."""
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))


def set_env_secret(key: str, value: str) -> None:
    """Persist a secret into .env and the current process."""
    p = ROOT / ".env"
    lines = p.read_text(encoding="utf-8").splitlines() if p.exists() else []
    lines = [l for l in lines if not l.startswith(key + "=")]
    lines.append(f'{key}="{value}"')
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.environ[key] = value
