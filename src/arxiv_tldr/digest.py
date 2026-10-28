"""Digest: render the email from stored data with Jinja2 templates."""

from datetime import date

from jinja2 import Environment, PackageLoader, select_autoescape

from .mailer import Message
from .selection import Selection


def authors_line(authors: list[str]) -> str:
    """First three authors, then "et al." when there are more."""
    shown = ", ".join(authors[:3])
    return f"{shown} et al." if len(authors) > 3 else shown


_env = Environment(
    loader=PackageLoader("arxiv_tldr", "templates"),
    autoescape=select_autoescape(["html"]),
    trim_blocks=True,
    lstrip_blocks=True,
)
_env.globals["authors_line"] = authors_line


def render_digest(
    announcement: date, selection: Selection, *, triaged_count: int, model: str,
    recipients: list[str],
) -> Message:
    context = {
        "announcement": announcement,
        "featured": selection.featured,
        "overflow": selection.overflow,
        "triaged_count": triaged_count,
        "model": model,
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
