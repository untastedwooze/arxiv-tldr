"""Pipeline: fetch -> triage -> summarize -> send for one Announcement date.

Each step is a function that does only the work with no stored result, so any step can be
rerun safely and ``run`` is just the steps in order.
"""

import logging
import time
from collections.abc import Callable
from datetime import date, datetime

import httpx

from .announcement import cutoff_time, current_announcement
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
# What makes a whole attempt worth retrying: the host, a feed, or the network is down.


class AttemptFailed(Exception):
    """An attempt finished without a usable result (nothing triaged, or Gmail rejected the send)."""


RETRYABLE = (OllamaUnreachable, FeedError, httpx.TransportError, AttemptFailed)


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
    store: Store, started: datetime | None = None, resend: bool = False,
) -> bool:
    """Send the Digest unless one was already sent (or ``resend``); marked sent only once the
    mailer accepts. A Digest for an Announcement before the current one is a Late Digest."""
    if store.digest_sent(announcement) and not resend:
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
        late=announcement < current_announcement(lambda: started, config),
        reconstructed=store.candidate_source(announcement) == "reconstructed",
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


def backfill(
    announcement: date, *, config: Config, client: httpx.Client, mailer: Mailer,
    clock: Callable[[], datetime], store: Store, sleep: Callable[[float], None],
    started: datetime,
) -> None:
    """Process a past Announcement once and send a Late Digest.

    Nothing blocks it (a stored Digest or Failure Notice is ignored and the Digest is sent
    again); stored Candidates, Triage results and Summaries are reused. There is no retry and no
    Failure Notice: a failure propagates to the caller.
    """
    log.info("backfilling Announcement %s with %s at %s",
             announcement, config.ollama_model, config.ollama_base_url)
    if not store.candidates(announcement):
        fetch(announcement, config=config, client=client, store=store,
              clock=lambda: started, sleep=sleep)
        if not store.candidates(announcement):
            log.info("no Candidates for %s; nothing to send", announcement)
            return
    triage_step(announcement, config=config, client=client, store=store)
    if not store.triaged(announcement):
        raise AttemptFailed("no Candidate could be triaged (invalid model output)")
    summarize_step(announcement, config=config, client=client, store=store)
    if not send_step(announcement, config=config, mailer=mailer, clock=clock, store=store,
                     started=started, resend=True):
        raise AttemptFailed("the mail server rejected the Digest")
    log.info("Late Digest for %s sent", announcement)


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
    if announcement < current_announcement(lambda: started, config):
        backfill(announcement, config=config, client=client, mailer=mailer, clock=clock,
                 store=store, sleep=sleep, started=started)
        return
    if store.digest_sent(announcement) or store.failure_notice(announcement) is not None:
        log.info("%s already handled; nothing to do", announcement)
        return
    log.info("processing Announcement %s with %s at %s",
             announcement, config.ollama_model, config.ollama_base_url)
    cutoff = cutoff_time(announcement, config)
    processed = False
    while True:
        try:
            if not processed:
                # Candidates already stored (an earlier attempt got this far) need no refetch.
                if not store.candidates(announcement):
                    fetch(announcement, config=config, client=client, store=store,
                          clock=lambda: started)
                    if not store.candidates(announcement):
                        log.info("no Candidates for %s; nothing to send", announcement)
                        return
                triage_step(announcement, config=config, client=client, store=store)
                if not store.triaged(announcement):
                    raise AttemptFailed("no Candidate could be triaged (invalid model output)")
                summarize_step(announcement, config=config, client=client, store=store)
                processed = True
            log.info("sending Digest for %s", announcement)
            send_step(
                announcement, config=config, mailer=mailer, clock=clock, store=store,
                started=started,
            )
            if not store.digest_sent(announcement):
                raise AttemptFailed("the mail server rejected the Digest")
            log.info("Digest for %s sent", announcement)
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
            log.info("retrying in %d minutes", config.retry_interval_minutes)
            sleep(config.retry_interval_minutes * 60)
