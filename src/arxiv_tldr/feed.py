"""Fetch step: read the Watched Categories' Candidates for an Announcement into the Store.

The current Announcement comes from the RSS feeds. A past one comes from arXiv's catchup
listing (exact) or, beyond catchup's window, is reconstructed from the API's submission dates.
"""

import html
import logging
import re
import time
from collections.abc import Callable
from datetime import date, datetime
from email.utils import parsedate_to_datetime

import feedparser
import httpx

from .announcement import EASTERN, current_announcement, listing_date_for, submission_window
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


def _urls(arxiv_id: str) -> dict[str, str]:
    return {
        "abs_url": f"https://arxiv.org/abs/{arxiv_id}",
        "html_url": f"https://arxiv.org/html/{arxiv_id}",
        "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}",
    }


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
                **_urls(arxiv_id),
            )
        )
    return candidates


def listing_date(xml: str) -> date:
    """The arXiv listing date a feed holds: its channel pubDate, as a US-Eastern date."""
    pub = feedparser.parse(xml).feed.get("published")
    if not pub:
        raise FeedError("malformed feed: no pubDate")
    try:
        return parsedate_to_datetime(pub).astimezone(EASTERN).date()
    except (TypeError, ValueError) as exc:
        raise FeedError(f"malformed feed: bad pubDate {pub!r}") from exc


# --- catchup listing: arxiv.org/catchup/<category>/<listing date>?abs=True ---

_TOTAL_RE = re.compile(r"Total of (\d+) entries for")
_SECTION_RE = re.compile(
    r"<h3>(New|Cross|Replacement) submissions \(showing (\d+) of (\d+) entries\)</h3>"
)
_ENTRY_ID_RE = re.compile(r'<a href ="/abs/(?P<id>[^"\s]+)"')
_TITLE_RE = re.compile(
    r"<div class='list-title[^']*'><span class='descriptor'>Title:</span>(?P<t>.*?)</div>",
    re.DOTALL,
)
_AUTHORS_RE = re.compile(r"<div class='list-authors'>(?P<a>.*?)</div>", re.DOTALL)
_SUBJECTS_RE = re.compile(
    r"<div class='list-subjects'>.*?</span>\s*"
    r'<span class="primary-subject">(?P<p>.*?)</span>(?P<rest>.*?)</div>',
    re.DOTALL,
)
_ABSTRACT_P_RE = re.compile(r"<p class='mathjax'>(?P<t>.*?)</p>", re.DOTALL)
_CODE_RE = re.compile(r"\(([^()]+)\)\s*$")


def _text(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", "", fragment)).split())


def _code(subject: str) -> str:
    match = _CODE_RE.search(_text(subject))
    if not match:
        raise FeedError(f"malformed catchup page: no category code in {subject!r}")
    return match.group(1)


def parse_catchup(page: str) -> list[Candidate]:
    """Candidates (new and cross-list entries only) on one catchup page.

    The page is undocumented HTML, so parsing is strict: anything unexpected, or a count that
    does not match the page's own totals, raises FeedError instead of yielding a partial set.
    """
    if "<div id='dlpage'>" not in page:
        raise FeedError("malformed catchup page: no listing")
    total = _TOTAL_RE.search(page)
    if not total:
        raise FeedError("malformed catchup page: no total")
    sections = list(_SECTION_RE.finditer(page))
    if int(total.group(1)) != sum(int(m.group(3)) for m in sections):
        raise FeedError("malformed catchup page: sections do not add up to the total")
    candidates = []
    for i, section in enumerate(sections):
        kind, shown, of = section.group(1), int(section.group(2)), int(section.group(3))
        if shown != of:
            raise FeedError("catchup page shows only part of a section (paginated)")
        end = sections[i + 1].start() if i + 1 < len(sections) else len(page)
        entries = page[section.end():end].split("<dt>")[1:]
        if len(entries) != of:
            raise FeedError(f"malformed catchup page: {len(entries)} entries, expected {of}")
        if kind != "Replacement":
            candidates += [_parse_catchup_entry(e, kind.lower()) for e in entries]
    return candidates


def _parse_catchup_entry(entry: str, announce_type: str) -> Candidate:
    parts = [
        _ENTRY_ID_RE.search(entry), _TITLE_RE.search(entry), _AUTHORS_RE.search(entry),
        _SUBJECTS_RE.search(entry), _ABSTRACT_P_RE.search(entry),
    ]
    if not all(parts):
        raise FeedError("malformed catchup page: an entry is missing a field")
    id_, title, authors, subjects, abstract = parts
    return Candidate(
        arxiv_id=id_.group("id"),
        title=_text(title.group("t")),
        authors=[_text(a) for a in re.findall(r"<a [^>]*>(.*?)</a>", authors.group("a"))],
        abstract=_text(abstract.group("t")),
        primary_category=_code(subjects.group("p")),
        cross_list_categories=[
            _code(s) for s in subjects.group("rest").split(";") if s.strip()
        ],
        announce_type=announce_type,
        **_urls(id_.group("id")),
    )


class CatchupUnavailable(Exception):
    """Catchup has no listing for that date (HTTP 400: older than its window)."""

    def __init__(self, url: str, reason: str):
        super().__init__(f"{url}: {reason}")
        self.url, self.reason = url, reason


# --- API reconstruction ---

API_PAGE_SIZE = 2000  # the API's maximum results per request


def _is_watched(category: str, watched: tuple[str, ...]) -> bool:
    return any(category == w or category.startswith(w + ".") for w in watched)


def parse_api(xml: str) -> tuple[list[Candidate], int]:
    """The Candidates in one API response (all "new" until classified) and its totalResults."""
    parsed = feedparser.parse(xml)
    try:
        total = int(parsed.feed["opensearch_totalresults"])
        candidates = []
        for entry in parsed.entries:
            arxiv_id = re.sub(r"v\d+$", "", entry.id.rsplit("/abs/", 1)[1])
            primary = entry.arxiv_primary_category["term"]
            candidates.append(
                Candidate(
                    arxiv_id=arxiv_id,
                    title=" ".join(entry.title.split()),
                    authors=[a.name for a in entry.get("authors", [])],
                    abstract=" ".join(entry.summary.split()),
                    primary_category=primary,
                    cross_list_categories=[
                        t["term"] for t in entry.get("tags", []) if t["term"] != primary
                    ],
                    announce_type="new",
                    **_urls(arxiv_id),
                )
            )
    except (AttributeError, KeyError, IndexError, ValueError) as exc:
        raise FeedError(f"malformed API response: {exc!r}") from exc
    return candidates, total


def _ok(response: httpx.Response, what: str) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise FeedError(f"{what} failed: HTTP {exc.response.status_code}") from exc


def _keep_best(merged: dict[str, Candidate], candidate: Candidate) -> None:
    seen = merged.get(candidate.arxiv_id)
    # A paper in several Watched Categories is one Candidate; "new" outranks "cross".
    if seen is None or (seen.announce_type == "cross" and candidate.announce_type == "new"):
        merged[candidate.arxiv_id] = candidate


def _fetch_rss(announcement: date, *, config: Config, client: httpx.Client) -> dict[str, Candidate]:
    merged: dict[str, Candidate] = {}
    for category in config.watched_categories:
        log.info("fetching feed %s", category)
        response = client.get(f"{config.rss_base_url}/{category}")
        _ok(response, f"feed {category}")
        expected = listing_date_for(announcement)
        actual = listing_date(response.text)
        if actual != expected:
            raise FeedError(
                f"feed {category} holds the {actual} listing, not the {expected} listing "
                f"of the {announcement} Announcement"
            )
        for candidate in parse_feed(response.text):
            _keep_best(merged, candidate)
    return merged


def _fetch_catchup(
    announcement: date, *, config: Config, client: httpx.Client, sleep: Callable[[float], None]
) -> dict[str, Candidate]:
    merged: dict[str, Candidate] = {}
    listing = listing_date_for(announcement)
    for i, category in enumerate(config.watched_categories):
        if i:
            sleep(config.catchup_delay_seconds)  # robots.txt Crawl-delay
        log.info("fetching catchup %s %s", category, listing)
        response = client.get(
            f"{config.arxiv_base_url}/catchup/{category}/{listing.isoformat()}",
            params={"abs": "True"},
        )
        if response.status_code == 400:
            raise CatchupUnavailable(str(response.url), f"HTTP 400 {response.text[:200].strip()!r}")
        _ok(response, f"catchup {category}")
        for candidate in parse_catchup(response.text):
            _keep_best(merged, candidate)
    return merged


def _reconstruct(
    announcement: date, *, config: Config, client: httpx.Client, sleep: Callable[[float], None]
) -> dict[str, Candidate]:
    window = submission_window(announcement)
    if window is None:
        return {}  # arXiv announces nothing on Friday and Saturday evenings
    stamp = lambda moment: moment.strftime("%Y%m%d%H%M")
    span = f"submittedDate:[{stamp(window[0])} TO {stamp(window[1])}]"
    merged: dict[str, Candidate] = {}
    requested = False
    for category in config.watched_categories:
        # `cat:` also matches cross-lists; an archive such as q-fin needs a wildcard.
        cat = f"cat:{category}" if "." in category else f"cat:{category}*"
        start = 0
        while True:
            if requested:
                sleep(config.api_delay_seconds)  # the API terms: one connection, spaced
            requested = True
            log.info("querying API for %s from result %d", category, start)
            response = client.get(
                f"{config.api_base_url}/api/query",
                params={
                    "search_query": f"{cat} AND {span}", "start": start,
                    "max_results": API_PAGE_SIZE, "sortBy": "submittedDate",
                    "sortOrder": "ascending",
                },
            )
            _ok(response, f"API query for {category}")
            found, total = parse_api(response.text)
            for c in found:
                watched = _is_watched(c.primary_category, config.watched_categories)
                _keep_best(merged, c.model_copy(update={"announce_type": "new" if watched else "cross"}))
            start += len(found)
            if not found or start >= total:
                break
    return merged


def fetch(
    announcement: date,
    *,
    config: Config,
    client: httpx.Client,
    store: Store,
    clock: Callable[[], datetime],
    sleep: Callable[[float], None] = time.sleep,
) -> list[Candidate]:
    """Record the Candidates of an Announcement; returns those found.

    The current Announcement is read from the RSS feeds; a feed still holding an earlier
    release raises FeedError and stores nothing. An earlier Announcement is a backfill: read
    from catchup, or reconstructed from the API when catchup no longer has the date. The
    Store remembers which source was used.
    """
    if announcement < current_announcement(clock, config):
        try:
            merged = _fetch_catchup(announcement, config=config, client=client, sleep=sleep)
            source = "catchup"
        except CatchupUnavailable as exc:
            log.warning("catchup refused %s (%s); reconstructing %s from the API",
                        exc.url, exc.reason, announcement)
            merged = _reconstruct(announcement, config=config, client=client, sleep=sleep)
            source = "reconstructed"
    else:
        merged = _fetch_rss(announcement, config=config, client=client)
        source = "rss"
    candidates = list(merged.values())
    log.info("fetched %d candidates for %s from %s", len(candidates), announcement, source)
    store.add_candidates(announcement, candidates)
    store.set_candidate_source(announcement, source)
    return candidates
