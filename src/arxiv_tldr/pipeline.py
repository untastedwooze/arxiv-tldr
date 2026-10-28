"""Pipeline: fetch -> triage -> select -> send for one Announcement date."""

from collections.abc import Callable
from datetime import date, datetime

import httpx

from .config import Config
from .digest import render_digest
from .feed import fetch
from .llm import OllamaClient
from .mailer import Mailer
from .selection import select
from .store import Store
from .triage import triage


def run(
    announcement: date,
    *,
    config: Config,
    client: httpx.Client,
    mailer: Mailer,
    clock: Callable[[], datetime],
    store: Store | None = None,
) -> None:
    """Process an Announcement end to end. Safe to rerun: finished work is skipped."""
    started = clock()
    store = store or Store(config.db_path)
    if store.digest_sent(announcement):
        return
    fetch(announcement, config=config, client=client, store=store, clock=clock)
    llm = OllamaClient(client, config.ollama_base_url, config.ollama_model)
    profile = config.interest_profile_path.read_text()
    triage(announcement, profile=profile, llm=llm, store=store)
    triaged = store.triaged(announcement)
    selection = select(triaged, threshold=config.threshold, cap=config.cap)
    message = render_digest(
        announcement, selection, triaged_count=len(triaged), model=config.ollama_model,
        recipients=list(config.recipients),
        duration_seconds=(clock() - started).total_seconds(),
        failure_count=len(store.candidates(announcement)) - len(triaged),
    )
    mailer.send(message)  # raises if not accepted; the Digest is then left unsent
    store.mark_digest_sent(
        announcement, featured=len(selection.featured), overflow=len(selection.overflow),
        sent_at=clock(),
    )
