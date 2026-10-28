"""Pipeline: fetch -> triage -> summarize -> send for one Announcement date.

Each step is a function that does only the work with no stored result, so any step can be
rerun safely and ``run`` is just the steps in order.
"""

import logging
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from .config import Config
from .digest import render_digest
from .feed import FeedError, fetch
from .llm import OllamaClient, OllamaUnreachable
from .mailer import Mailer
from .notice import render_failure_notice
from .selection import select
from .store import Store
from .summarize import summarize
from .triage import triage

log = logging.getLogger(__name__)
EASTERN = ZoneInfo("America/New_York")
# What makes a whole attempt worth retrying: the host, a feed, or the network is down.


class AttemptFailed(Exception):
    """An attempt finished without a usable result (nothing triaged, or Gmail rejected the send)."""


RETRYABLE = (OllamaUnreachable, FeedError, httpx.TransportError, AttemptFailed)


def current_announcement(clock: Callable[[], datetime], config: Config) -> date:
    """The Announcement whose retry window is open now: before the cutoff time (Eastern) it is
    still the previous day's, so a catch-up run after midnight resolves correctly."""
    hour, minute = map(int, config.cutoff.split(":"))
    now = clock().astimezone(EASTERN)
    return (now - timedelta(hours=hour, minutes=minute)).date()


def cutoff_time(announcement: date, config: Config) -> datetime:
    """When to stop retrying: the configured Eastern time on the morning after."""
    hour, minute = map(int, config.cutoff.split(":"))
    morning = announcement + timedelta(days=1)
    return datetime(morning.year, morning.month, morning.day, hour, minute, tzinfo=EASTERN)


def triage_step(
    announcement: date, *, config: Config, client: httpx.Client, store: Store
) -> int:
    """Score the Candidates that have no stored result; returns how many were scored."""
    llm = OllamaClient(client, config.ollama_base_url, config.ollama_model)
    profile = config.interest_profile_path.read_text()
    return triage(announcement, profile=profile, llm=llm, store=store)


def summarize_step(
    announcement: date, *, config: Config, client: httpx.Client, store: Store
) -> int:
    """Summarize the Featured Papers that have no stored Summary; returns how many were written."""
    llm = OllamaClient(client, config.ollama_base_url, config.ollama_model)
    profile = config.interest_profile_path.read_text()
    selection = select(store.triaged(announcement), threshold=config.threshold, cap=config.cap)
    return summarize(
        announcement, selection.featured, profile=profile, llm=llm, store=store, client=client,
        num_ctx=config.num_ctx,
        text_budget=config.text_budget_chars,
    )


def send_step(
    announcement: date, *, config: Config, mailer: Mailer, clock: Callable[[], datetime],
    store: Store, started: datetime | None = None,
) -> bool:
    """Send the Digest unless one was already sent; marked sent only once the mailer accepts."""
    if store.digest_sent(announcement):
        return False
    started = started or clock()
    triaged = store.triaged(announcement)
    selection = select(triaged, threshold=config.threshold, cap=config.cap)
    summaries = store.summaries(announcement)
    summary_failures = sum(1 for t in selection.featured if t.candidate.arxiv_id not in summaries)
    message = render_digest(
        announcement, selection, summaries=summaries, triaged_count=len(triaged),
        model=config.ollama_model, recipients=list(config.recipients),
        duration_seconds=(clock() - started).total_seconds(),
        failure_count=len(store.candidates(announcement)) - len(triaged) + summary_failures,
    )
    try:
        mailer.send(message)
    except Exception:
        # Left unsent so a later attempt can retry; the log is the only signal if Gmail is down.
        log.exception("mailer rejected the Digest for %s", announcement)
        return False
    store.mark_digest_sent(
        announcement, featured=len(selection.featured), overflow=len(selection.overflow),
        sent_at=clock(),
    )
    return True


def send_failure_notice(
    announcement: date, *, reason: str, config: Config, mailer: Mailer,
    clock: Callable[[], datetime], store: Store,
) -> None:
    """Send a Failure Notice (once) and record it against the Announcement date."""
    if store.failure_notice(announcement) is not None:
        return
    message = render_failure_notice(
        announcement, reason=reason, recipients=list(config.recipients)
    )
    try:
        mailer.send(message)
    except Exception:
        log.exception("mailer rejected the Failure Notice for %s: %s", announcement, reason)
        return
    store.record_failure_notice(announcement, reason=reason, sent_at=clock())


def run(
    announcement: date,
    *,
    config: Config,
    client: httpx.Client,
    mailer: Mailer,
    clock: Callable[[], datetime],
    store: Store | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Process an Announcement end to end. Safe to rerun: finished work is skipped.

    If piglet or the feeds are failing, retry every ``retry_interval_minutes`` until the
    cutoff, then send a Failure Notice. Empty feeds mean there was no Announcement: send nothing.
    """
    started = clock()
    store = store or Store(config.db_path)
    if store.digest_sent(announcement) or store.failure_notice(announcement) is not None:
        return
    cutoff = cutoff_time(announcement, config)
    processed = False
    while True:
        try:
            if not processed:
                # Candidates already stored (an earlier attempt got this far) need no refetch.
                if not store.candidates(announcement):
                    fetch(announcement, config=config, client=client, store=store, clock=clock)
                    if not store.candidates(announcement):
                        return
                triage_step(announcement, config=config, client=client, store=store)
                if not store.triaged(announcement):
                    raise AttemptFailed("no Candidate could be triaged (invalid model output)")
                summarize_step(announcement, config=config, client=client, store=store)
                processed = True
            send_step(
                announcement, config=config, mailer=mailer, clock=clock, store=store,
                started=started,
            )
            if not store.digest_sent(announcement):
                raise AttemptFailed("the mail server rejected the Digest")
            return
        except RETRYABLE as exc:
            log.warning("attempt for %s failed: %s", announcement, exc)
            if clock() >= cutoff:
                # If Gmail is the problem the notice cannot help; it is logged either way.
                send_failure_notice(
                    announcement, reason=str(exc), config=config, mailer=mailer,
                    clock=clock, store=store,
                )
                return
            sleep(config.retry_interval_minutes * 60)
