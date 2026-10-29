"""Command-line entry point: ``arxiv-tldr fetch YYYY-MM-DD``."""

import argparse
import logging
import sys
import time
from collections.abc import Callable, Sequence
from contextlib import nullcontext
from datetime import date, datetime, timezone

import httpx

from .announcement import current_announcement
from .config import ConfigError, load_config
from .feed import fetch
from .mailer import GmailMailer, Mailer
from .pipeline import run, send_step, summarize_step, triage_step
from .store import Store


def configure_logging(verbose: bool) -> None:
    """Log progress to stderr (so it reaches the systemd journal) when ``verbose``."""
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    client: httpx.Client | None = None,
    clock: Callable[[], datetime] | None = None,
    mailer: Mailer | None = None,
    sleep: Callable[[float], None] | None = None,
) -> int:
    """Run a subcommand. ``client``, ``clock`` and ``mailer`` are the injected seams."""
    parser = argparse.ArgumentParser(prog="arxiv-tldr")
    parser.add_argument("-v", "--verbose", action="store_true", help="Log progress to stderr")
    sub = parser.add_subparsers(dest="command", required=True)
    fetch_parser = sub.add_parser("fetch", help="Fetch an Announcement's Candidates into the Store")
    fetch_parser.add_argument("announcement", type=date.fromisoformat, help="Announcement date")
    run_parser = sub.add_parser("run", help="Fetch, triage, select and send an Announcement's Digest")
    run_parser.add_argument(
        "announcement", type=date.fromisoformat, nargs="?",
        help="Announcement date (default: today in America/New_York)",
    )
    for name, text in (
        ("triage", "Triage an Announcement's untriaged Candidates"),
        ("summarize", "Summarize an Announcement's Featured Papers"),
        ("send", "Send an Announcement's Digest unless already sent"),
    ):
        step_parser = sub.add_parser(name, help=text)
        step_parser.add_argument("announcement", type=date.fromisoformat, help="Announcement date")
    args = parser.parse_args(argv)
    configure_logging(args.verbose)

    config = load_config()
    clock = clock or (lambda: datetime.now(timezone.utc))
    if args.command in ("run", "send"):
        try:
            config.require_mail(credentials=mailer is None)
        except ConfigError as exc:
            print(f"arxiv-tldr: {exc}", file=sys.stderr)
            return 2
    # An injected client belongs to the caller, so it is not closed here.
    with nullcontext(client) if client else httpx.Client(timeout=30, follow_redirects=True) as http:
        if args.command == "run":
            mailer = mailer or GmailMailer(config.gmail_address, config.gmail_app_password)
            current = current_announcement(clock, config)
            announcement = args.announcement or current
            if announcement > current:
                print(
                    f"arxiv-tldr: {announcement} is in the future; the current Announcement "
                    f"is {current}", file=sys.stderr,
                )
                return 2
            try:
                run(
                    announcement, config=config, client=http, mailer=mailer, clock=clock,
                    sleep=sleep or time.sleep,
                )
            except Exception as exc:
                # Only a backfill raises (the nightly run retries and sends a Failure Notice),
                # and whatever it raises is reported as a reason, not a traceback.
                logging.getLogger(__name__).debug("backfill failed", exc_info=True)
                print(f"arxiv-tldr: {exc or type(exc).__name__}", file=sys.stderr)
                return 1
            return 0
        if args.command in ("triage", "summarize", "send"):
            store = Store(config.db_path)
            if args.command == "triage":
                n = triage_step(args.announcement, config=config, client=http, store=store)
                print(f"{args.announcement}: {n} candidates triaged")
            elif args.command == "summarize":
                n = summarize_step(args.announcement, config=config, client=http, store=store)
                print(f"{args.announcement}: {n} summaries written")
            else:
                mailer = mailer or GmailMailer(config.gmail_address, config.gmail_app_password)
                sent = send_step(
                    args.announcement, config=config, mailer=mailer, clock=clock, store=store
                )
                print(f"{args.announcement}: {'sent' if sent else 'already sent'}")
            return 0
        candidates = fetch(
            args.announcement, config=config, client=http, store=Store(config.db_path), clock=clock,
            sleep=sleep or time.sleep,
        )
    print(f"{args.announcement}: {len(candidates)} candidates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
