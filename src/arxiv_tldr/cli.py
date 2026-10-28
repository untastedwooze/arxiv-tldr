"""Command-line entry point: ``arxiv-tldr fetch YYYY-MM-DD``."""

import argparse
from collections.abc import Callable, Sequence
from datetime import date, datetime, timezone

import httpx

from .config import load_config
from .feed import fetch
from .mailer import GmailMailer, Mailer
from .pipeline import run
from .store import Store


def main(
    argv: Sequence[str] | None = None,
    *,
    client: httpx.Client | None = None,
    clock: Callable[[], datetime] | None = None,
    mailer: Mailer | None = None,
) -> int:
    """Run a subcommand. ``client``, ``clock`` and ``mailer`` are the injected seams."""
    parser = argparse.ArgumentParser(prog="arxiv-tldr")
    sub = parser.add_subparsers(dest="command", required=True)
    fetch_parser = sub.add_parser("fetch", help="Fetch an Announcement's Candidates into the Store")
    fetch_parser.add_argument("announcement", type=date.fromisoformat, help="Announcement date")
    run_parser = sub.add_parser("run", help="Fetch, triage, select and send an Announcement's Digest")
    run_parser.add_argument("announcement", type=date.fromisoformat, help="Announcement date")
    args = parser.parse_args(argv)

    config = load_config()
    clock = clock or (lambda: datetime.now(timezone.utc))
    with client or httpx.Client(timeout=30, follow_redirects=True) as http:
        if args.command == "run":
            mailer = mailer or GmailMailer(config.gmail_address, config.gmail_app_password)
            run(args.announcement, config=config, client=http, mailer=mailer, clock=clock)
            return 0
        candidates = fetch(
            args.announcement, config=config, client=http, store=Store(config.db_path), clock=clock
        )
    print(f"{args.announcement}: {len(candidates)} candidates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
