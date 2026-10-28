"""Digest: render the email from stored data with Jinja2 templates."""

from datetime import date

from jinja2 import Environment, PackageLoader, select_autoescape

from .mailer import Message
from .selection import Selection
from .store import StoredSummary
from .summarize import SUMMARY_LABELS


def authors_line(authors: list[str]) -> str:
    """First three authors, then "et al." when there are more."""
    shown = ", ".join(authors[:3])
    return f"{shown} et al." if len(authors) > 3 else shown


def format_duration(seconds: float) -> str:
    whole = round(seconds)
    minutes, secs = divmod(whole, 60)
    return f"{minutes}m {secs}s" if minutes else f"{secs}s"


_env = Environment(
    loader=PackageLoader("arxiv_tldr", "templates"),
    autoescape=select_autoescape(["html"]),
    trim_blocks=True,
    lstrip_blocks=True,
)
_env.globals["authors_line"] = authors_line
_env.globals["summary_labels"] = SUMMARY_LABELS


def render_digest(
    announcement: date, selection: Selection, *, summaries: dict[str, StoredSummary],
    triaged_count: int, model: str,
    recipients: list[str], duration_seconds: float = 0, failure_count: int = 0,
) -> Message:
    context = {
        "announcement": announcement,
        "announcement_label": f"{announcement:%a %Y-%m-%d}",
        "featured": selection.featured,
        "overflow": selection.overflow,
        "summaries": summaries,
        "triaged_count": triaged_count,
        "model": model,
        "run_time": format_duration(duration_seconds),
        "failure_count": failure_count,
    }
    subject = (
        f"arxiv-tldr · {announcement:%a %Y-%m-%d} · {len(selection.featured)} featured / "
        f"{len(selection.overflow)} overflow / {triaged_count} triaged"
    )
    return Message(
        subject=subject,
        html=_env.get_template("digest.html.j2").render(**context),
        text=_env.get_template("digest.txt.j2").render(**context),
        recipients=recipients,
    )
