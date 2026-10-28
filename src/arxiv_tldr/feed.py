"""Fetch step: read the arXiv RSS feeds of the Watched Categories into Candidates."""

import re
from collections.abc import Callable
from datetime import date, datetime

import feedparser
import httpx

from .config import Config
from .store import Candidate, Store

KEPT_TYPES = {"new", "cross"}  # drops "replace" and "replace-cross"
_ID_RE = re.compile(r"^arXiv:(?P<id>\S+?)v\d+\s+Announce Type:")
_ABSTRACT_RE = re.compile(r"Abstract:\s*(?P<text>.*)", re.DOTALL)


class FeedError(Exception):
    """A feed could not be fetched or understood."""


def parse_feed(xml: str) -> list[Candidate]:
    """Candidates (new and cross-list entries only) in one feed document."""
    try:
        return _parse_feed(xml)
    except (AttributeError, KeyError, IndexError) as exc:
        raise FeedError(f"malformed feed: {exc!r}") from exc


def _parse_feed(xml: str) -> list[Candidate]:
    candidates = []
    for entry in feedparser.parse(xml).entries:
        announce_type = entry.get("arxiv_announce_type", "")
        if announce_type not in KEPT_TYPES:
            continue
        arxiv_id = _ID_RE.match(entry.summary.strip()).group("id")
        abstract = _ABSTRACT_RE.search(entry.summary).group("text").strip()
        categories = [t["term"] for t in entry.get("tags", [])]
        candidates.append(
            Candidate(
                arxiv_id=arxiv_id,
                title=" ".join(entry.title.split()),
                authors=[a.strip() for a in entry.get("author", "").split(",") if a.strip()],
                abstract=" ".join(abstract.split()),
                primary_category=categories[0],
                cross_list_categories=categories[1:],
                announce_type=announce_type,
                abs_url=f"https://arxiv.org/abs/{arxiv_id}",
                html_url=f"https://arxiv.org/html/{arxiv_id}",
                pdf_url=f"https://arxiv.org/pdf/{arxiv_id}",
            )
        )
    return candidates


def fetch(
    announcement: date,
    *,
    config: Config,
    client: httpx.Client,
    store: Store,
    clock: Callable[[], datetime],
) -> list[Candidate]:
    """Record the Candidates of an Announcement; returns those found in the feeds.

    ``clock`` is part of the seam for later date-validation logic; unused so far.
    """
    merged: dict[str, Candidate] = {}
    for category in config.watched_categories:
        response = client.get(f"{config.rss_base_url}/{category}")
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise FeedError(f"feed {category} failed: HTTP {exc.response.status_code}") from exc
        for candidate in parse_feed(response.text):
            seen = merged.get(candidate.arxiv_id)
            # A paper in several Watched Categories is one Candidate; "new" outranks "cross".
            if seen is None or (seen.announce_type == "cross" and candidate.announce_type == "new"):
                merged[candidate.arxiv_id] = candidate
    candidates = list(merged.values())
    store.add_candidates(announcement, candidates)
    return candidates
