"""Opt-in smoke test: run a real Announcement against real Ollama and report timings.

``python -m arxiv_tldr.smoke`` (or ``scripts/smoke_piglet.py``) uses the real httpx client and
a recording Mailer, so no email is sent unless ``--send`` is given. The reporting is in
``smoke_report`` / ``format_report`` so it can be tested against a pre-populated Store.
"""

import argparse
import tempfile
from collections import Counter
from collections.abc import Sequence
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
from pydantic import BaseModel

from .cli import configure_logging
from .config import load_config
from .mailer import GmailMailer, Message
from .pipeline import run
from .store import CallTiming, Store


class TimingStats(BaseModel):
    count: int
    total_seconds: float
    mean_seconds: float
    max_seconds: float


class SmokeReport(BaseModel):
    triage: TimingStats
    summary: TimingStats
    score_distribution: dict[int, int]  # Relevance Score -> number of Candidates
    source_breakdown: dict[str, int]  # html / pdf / abstract Summaries, plus how many were cut


def _stats(timings: list[CallTiming], kind: str) -> TimingStats:
    seconds = [t.seconds for t in timings if t.kind == kind]
    total = sum(seconds)
    return TimingStats(
        count=len(seconds), total_seconds=total,
        mean_seconds=total / len(seconds) if seconds else 0.0,
        max_seconds=max(seconds, default=0.0),
    )


def smoke_report(store: Store, announcement: date) -> SmokeReport:
    timings = store.call_timings(announcement)
    scores = Counter(t.score for t in store.triaged(announcement))
    summaries = store.summaries(announcement).values()
    sources = {"html": 0, "pdf": 0, "abstract": 0}
    for s in summaries:
        sources[s.source] = sources.get(s.source, 0) + 1
    sources["cut"] = sum(1 for s in summaries if s.cut)
    return SmokeReport(
        triage=_stats(timings, "triage"), summary=_stats(timings, "summary"),
        score_distribution=dict(sorted(scores.items())), source_breakdown=sources,
    )


def format_report(report: SmokeReport, timings: list[CallTiming]) -> str:
    lines = ["Per-call timings"]
    lines += [f"  {t.kind:<7} {t.arxiv_id:<14} {t.seconds:.1f}s" for t in timings]
    lines += ["", "Totals"]
    for kind, s in (("triage", report.triage), ("summary", report.summary)):
        lines.append(
            f"  {kind:<7}  {s.count}  total {s.total_seconds:.1f}s  "
            f"mean {s.mean_seconds:.1f}s  max {s.max_seconds:.1f}s"
        )
    lines += ["", "Relevance Score distribution"]
    lines += [f"  score {s:>2}: {n}" for s, n in report.score_distribution.items()]
    lines += ["", "Summary sources"]
    lines += [f"  {k}: {n}" for k, n in report.source_breakdown.items()]
    return "\n".join(lines)


class RecordingMailer:
    """Stands in for Gmail: remembers the Digest instead of sending it."""

    def __init__(self):
        self.sent: list[Message] = []

    def send(self, message: Message) -> None:
        self.sent.append(message)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arxiv-tldr-smoke", description=__doc__)
    parser.add_argument("--date", type=date.fromisoformat, default=date.today(),
                        help="Announcement date (default: today)")
    parser.add_argument("--db", type=Path, help="Store path (default: a fresh temp file)")
    parser.add_argument("--send", action="store_true", help="Really email the Digest via Gmail")
    parser.add_argument("-q", "--quiet", action="store_true", help="Suppress progress logging")
    args = parser.parse_args(argv)
    configure_logging(not args.quiet)

    config = load_config()
    db_path = args.db or Path(tempfile.mkdtemp(prefix="arxiv-tldr-smoke-")) / "smoke.db"
    config = config.model_copy(update={"db_path": db_path})
    mailer = (
        GmailMailer(config.gmail_address, config.gmail_app_password)
        if args.send else RecordingMailer()
    )
    store = Store(db_path)
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        run(args.date, config=config, client=client, mailer=mailer,
            clock=lambda: datetime.now(timezone.utc), store=store)
    print(f"Store: {db_path}")
    print(format_report(smoke_report(store, args.date), store.call_timings(args.date)))
    if isinstance(mailer, RecordingMailer):
        print("\nNo email sent (use --send). Digest subjects:", [m.subject for m in mailer.sent])
        for i, message in enumerate(mailer.sent):
            html_path = db_path.with_name(f"digest-{args.date}{f'-{i}' if i else ''}.html")
            html_path.write_text(message.html)
            print(f"Digest HTML ({len(message.html.encode()) // 1024} KB): {html_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
