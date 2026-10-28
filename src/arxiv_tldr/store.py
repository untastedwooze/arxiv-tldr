"""The SQLite Store. Owns the schema; everything is keyed by Announcement date."""

import json
import sqlite3
from datetime import date, datetime
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
CREATE TABLE IF NOT EXISTS triage_results (
    announcement_date TEXT NOT NULL,
    arxiv_id TEXT NOT NULL,
    score INTEGER NOT NULL,
    rationale TEXT NOT NULL,
    model TEXT NOT NULL,
    seconds REAL NOT NULL,
    PRIMARY KEY (announcement_date, arxiv_id)
);
CREATE TABLE IF NOT EXISTS call_timings (
    announcement_date TEXT NOT NULL,
    kind TEXT NOT NULL,                  -- "triage" or "summary"
    arxiv_id TEXT NOT NULL,
    seconds REAL NOT NULL,
    PRIMARY KEY (announcement_date, kind, arxiv_id)
);
CREATE TABLE IF NOT EXISTS digests (
    announcement_date TEXT PRIMARY KEY,
    featured_count INTEGER NOT NULL,
    overflow_count INTEGER NOT NULL,
    sent_at TEXT                         -- NULL until the mail server accepts the message
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


class TriagedCandidate(BaseModel):
    candidate: Candidate
    score: int
    rationale: str
    model: str


class CallTiming(BaseModel):
    kind: str  # "triage" or "summary"
    arxiv_id: str
    seconds: float


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

    def untriaged(self, announcement: date) -> list[Candidate]:
        done = {
            row["arxiv_id"]
            for row in self._db.execute(
                "SELECT arxiv_id FROM triage_results WHERE announcement_date = ?",
                (announcement.isoformat(),),
            )
        }
        return [c for c in self.candidates(announcement) if c.arxiv_id not in done]

    def add_triage_result(
        self, announcement: date, arxiv_id: str, *, score: int, rationale: str, model: str,
        seconds: float,
    ) -> None:
        with self._db:
            self._db.execute(
                "INSERT OR IGNORE INTO triage_results VALUES (?,?,?,?,?,?)",
                (announcement.isoformat(), arxiv_id, score, rationale, model, seconds),
            )
        self.add_call_timing(announcement, "triage", arxiv_id, seconds)

    def add_call_timing(
        self, announcement: date, kind: str, arxiv_id: str, seconds: float
    ) -> None:
        """Record how long one LLM call took (kind: "triage" or "summary")."""
        with self._db:
            self._db.execute(
                "INSERT OR IGNORE INTO call_timings VALUES (?,?,?,?)",
                (announcement.isoformat(), kind, arxiv_id, seconds),
            )

    def call_timings(self, announcement: date) -> list[CallTiming]:
        rows = self._db.execute(
            "SELECT kind, arxiv_id, seconds FROM call_timings WHERE announcement_date = ? "
            "ORDER BY kind DESC, arxiv_id",
            (announcement.isoformat(),),
        )
        return [CallTiming(**dict(r)) for r in rows]

    def triaged(self, announcement: date) -> list[TriagedCandidate]:
        by_id = {c.arxiv_id: c for c in self.candidates(announcement)}
        rows = self._db.execute(
            "SELECT * FROM triage_results WHERE announcement_date = ? ORDER BY arxiv_id",
            (announcement.isoformat(),),
        )
        return [
            TriagedCandidate(
                candidate=by_id[r["arxiv_id"]],
                score=r["score"], rationale=r["rationale"], model=r["model"],
            )
            for r in rows
        ]

    def digest_sent(self, announcement: date) -> bool:
        row = self._db.execute(
            "SELECT sent_at FROM digests WHERE announcement_date = ?",
            (announcement.isoformat(),),
        ).fetchone()
        return row is not None and row["sent_at"] is not None

    def mark_digest_sent(
        self, announcement: date, *, featured: int, overflow: int, sent_at: datetime
    ) -> None:
        with self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO digests VALUES (?,?,?,?)",
                (announcement.isoformat(), featured, overflow, sent_at.isoformat()),
            )


_JSON_FIELDS = {"authors", "cross_list_categories"}
