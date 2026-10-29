"""Fetch step: read the arXiv RSS feeds of the Watched Categories into Candidates."""

import logging
import re
from collections.abc import Callable
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

import feedparser
import httpx

from .config import Config
from .store import Candidate, Store

log = logging.getLogger(__name__)

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


_EASTERN = ZoneInfo("America/New_York")


def listing_date(xml: str) -> date:
    """The arXiv listing date a feed holds: its channel pubDate, as a US-Eastern date."""
    pub = feedparser.parse(xml).feed.get("published")
    if not pub:
        raise FeedError("malformed feed: no pubDate")
    try:
        return parsedate_to_datetime(pub).astimezone(_EASTERN).date()
    except (TypeError, ValueError) as exc:
        raise FeedError(f"malformed feed: bad pubDate {pub!r}") from exc


def fetch(
    announcement: date,
    *,
    config: Config,
    client: httpx.Client,
    store: Store,
    clock: Callable[[], datetime],
) -> list[Candidate]:
    """Record the Candidates of an Announcement; returns those found in the feeds.

    A feed still holding an earlier release raises FeedError and stores nothing. ``clock`` is
    unused: the check compares the feed against the requested Announcement only.
    """
    merged: dict[str, Candidate] = {}
    for category in config.watched_categories:
        log.info("fetching feed %s", category)
        response = client.get(f"{config.rss_base_url}/{category}")
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise FeedError(f"feed {category} failed: HTTP {exc.response.status_code}") from exc
        expected = announcement + timedelta(days=1)  # arXiv labels a release with the next day
        actual = listing_date(response.text)
        if actual != expected:
            raise FeedError(
                f"feed {category} holds the {actual} listing, not the {expected} listing "
                f"of the {announcement} Announcement"
            )
        for candidate in parse_feed(response.text):
            seen = merged.get(candidate.arxiv_id)
            # A paper in several Watched Categories is one Candidate; "new" outranks "cross".
            if seen is None or (seen.announce_type == "cross" and candidate.announce_type == "new"):
                merged[candidate.arxiv_id] = candidate
    candidates = list(merged.values())
    log.info("fetched %d candidates for %s", len(candidates), announcement)
    store.add_candidates(announcement, candidates)
    return candidates
