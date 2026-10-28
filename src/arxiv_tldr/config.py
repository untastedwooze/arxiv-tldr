"""Settings: defaults, overlaid by an optional config.toml, then by environment / .env.

Environment variables are named ``ARXIV_TLDR_<FIELD>`` (e.g. ``ARXIV_TLDR_DB_PATH``);
list fields are comma-separated. Later tickets add their own fields here.
"""

import os
import tomllib
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict

DEFAULT_WATCHED_CATEGORIES = ("q-fin", "stat.ME", "stat.AP", "stat.CO", "stat.ML")
ENV_PREFIX = "ARXIV_TLDR_"


class Config(BaseModel):
    model_config = ConfigDict(frozen=True)

    watched_categories: tuple[str, ...] = DEFAULT_WATCHED_CATEGORIES
    db_path: Path = Path("arxiv-tldr.db")
    rss_base_url: str = "https://rss.arxiv.org/rss"


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
