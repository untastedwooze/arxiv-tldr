"""The SQLite Store. Owns the schema; everything is keyed by Announcement date."""

import json
import sqlite3
from datetime import date
from pathlib import Path

from pydantic import BaseModel

SCHEMA = """
CREATE TABLE IF NOT EXISTS candidates (
    announcement_date TEXT NOT NULL,
    arxiv_id TEXT NOT NULL,
    title TEXT NOT NULL,
    authors TEXT NOT NULL,              -- JSON list
    abstract TEXT NOT NULL,
    primary_category TEXT NOT NULL,
    cross_list_categories TEXT NOT NULL, -- JSON list
    announce_type TEXT NOT NULL,
    abs_url TEXT NOT NULL,
    html_url TEXT NOT NULL,
    pdf_url TEXT NOT NULL,
    PRIMARY KEY (announcement_date, arxiv_id)
);
"""


class Candidate(BaseModel):
    arxiv_id: str
    title: str
    authors: list[str]
    abstract: str
    primary_category: str
    cross_list_categories: list[str]
    announce_type: str  # "new" or "cross"
    abs_url: str
    html_url: str
    pdf_url: str


class Store:
    def __init__(self, path: Path):
        self._db = sqlite3.connect(path)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)

    def add_candidates(self, announcement: date, candidates: list[Candidate]) -> None:
        """Record Candidates for an Announcement; ones already stored are left as they are."""
        with self._db:
            self._db.executemany(
                "INSERT OR IGNORE INTO candidates VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        announcement.isoformat(),
                        c.arxiv_id,
                        c.title,
                        json.dumps(c.authors),
                        c.abstract,
                        c.primary_category,
                        json.dumps(c.cross_list_categories),
                        c.announce_type,
                        c.abs_url,
                        c.html_url,
                        c.pdf_url,
                    )
                    for c in candidates
                ],
            )

    def candidates(self, announcement: date) -> list[Candidate]:
        rows = self._db.execute(
            "SELECT * FROM candidates WHERE announcement_date = ? ORDER BY arxiv_id",
            (announcement.isoformat(),),
        )
        return [
            Candidate(
                **{k: row[k] for k in Candidate.model_fields if k not in _JSON_FIELDS},
                authors=json.loads(row["authors"]),
                cross_list_categories=json.loads(row["cross_list_categories"]),
            )
            for row in rows
        ]


_JSON_FIELDS = {"authors", "cross_list_categories"}
