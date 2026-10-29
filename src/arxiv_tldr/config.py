"""Settings: defaults, overlaid by an optional config.toml, then by environment / .env.

Environment variables are named ``ARXIV_TLDR_<FIELD>`` (e.g. ``ARXIV_TLDR_DB_PATH``);
list fields are comma-separated. Later tickets add their own fields here.
"""

import os
import tomllib
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict

DEFAULT_WATCHED_CATEGORIES = ("q-fin", "stat.ME", "econ.EM")
CONTEXT_RESERVE_TOKENS = 4096  # profile, instructions and the generated Summary
CHARS_PER_TOKEN = 3
ENV_PREFIX = "ARXIV_TLDR_"


class ConfigError(Exception):
    """A setting needed by the command is missing."""


class Config(BaseModel):
    model_config = ConfigDict(frozen=True)

    watched_categories: tuple[str, ...] = DEFAULT_WATCHED_CATEGORIES
    db_path: Path = Path("arxiv-tldr.db")
    rss_base_url: str = "https://rss.arxiv.org/rss"
    interest_profile_path: Path = Path("interest-profile.md")
    ollama_base_url: str = "http://piglet.tail2598b1.ts.net:11434"
    ollama_model: str = "qwen3:30b-a3b-instruct-2507-q4_K_M"
    threshold: int = 7
    cap: int = 15
    cutoff: str = "04:00"  # US Eastern, the morning after the Announcement
    retry_interval_minutes: int = 20
    num_ctx: int = 32768  # context window requested for every Summary call
    # Max characters of paper text in a Summary prompt; None derives it from num_ctx.
    summary_text_budget: int | None = None
    recipients: tuple[str, ...] = ()
    gmail_address: str = ""
    gmail_app_password: str = ""

    def require_mail(self, *, credentials: bool) -> None:
        """Fail fast if the settings needed to send mail are missing."""
        missing = [
            ENV_PREFIX + name.upper()
            for name, value in (
                ("recipients", self.recipients),
                *((("gmail_address", self.gmail_address),
                   ("gmail_app_password", self.gmail_app_password)) if credentials else ()),
            )
            if not value
        ]
        if missing:
            raise ConfigError(f"missing mail settings: {', '.join(missing)}")

    @property
    def text_budget_chars(self) -> int:
        """Characters of paper text that fit: num_ctx less room for the prompt and the answer,
        at roughly 3 characters per token."""
        if self.summary_text_budget is not None:
            return self.summary_text_budget
        return max(0, self.num_ctx - CONTEXT_RESERVE_TOKENS) * CHARS_PER_TOKEN


def load_config(config_file: Path = Path("config.toml"), env_file: Path = Path(".env")) -> Config:
    """Build a Config from config file, then .env / environment (which win)."""
    values: dict = {}
    if config_file.exists():
        values.update(tomllib.loads(config_file.read_text()))
    load_dotenv(env_file)  # does not override variables already in the environment
    for name, field in Config.model_fields.items():
        raw = os.environ.get(ENV_PREFIX + name.upper())
        if raw is None:
            continue
        values[name] = (
            [part.strip() for part in raw.split(",") if part.strip()]
            if field.annotation == tuple[str, ...]
            else raw
        )
    return Config(**values)
