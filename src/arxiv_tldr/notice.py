"""The Failure Notice: a short email sent in place of a Digest."""

from datetime import date
from html import escape

from .mailer import Message


def render_failure_notice(announcement: date, *, reason: str, recipients: list[str]) -> Message:
    subject = f"arxiv-tldr · {announcement:%a %Y-%m-%d} · FAILED: no digest"
    text = (
        f"No Digest could be produced for the {announcement.isoformat()} Announcement.\n\n"
        f"Reason: {reason}\n"
    )
    html = (
        f"<p>No Digest could be produced for the {announcement.isoformat()} Announcement.</p>"
        f"<p><strong>Reason:</strong> {escape(reason)}</p>"
    )
    return Message(subject=subject, html=html, text=text, recipients=recipients)
