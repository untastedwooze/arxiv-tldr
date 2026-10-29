"""Announcement dates: which one is current, when its retry window closes, and arXiv's labels.

An Announcement is named by the US-Eastern date of the evening it is released; arXiv's
listings label the same release with the following day.
"""

from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .config import Config

EASTERN = ZoneInfo("America/New_York")


def listing_date_for(announcement: date) -> date:
    """The date arXiv's listings (RSS pubDate, catchup) give the Announcement's release."""
    return announcement + timedelta(days=1)


def _cutoff_hm(config: Config) -> tuple[int, int]:
    hour, minute = map(int, config.cutoff.split(":"))
    return hour, minute


def current_announcement(clock: Callable[[], datetime], config: Config) -> date:
    """The Announcement whose retry window is open now: before the cutoff time (Eastern) it is
    still the previous day's, so a catch-up run after midnight resolves correctly."""
    hour, minute = _cutoff_hm(config)
    now = clock().astimezone(EASTERN)
    return (now - timedelta(hours=hour, minutes=minute)).date()


def cutoff_time(announcement: date, config: Config) -> datetime:
    """When to stop retrying: the configured Eastern time on the morning after."""
    hour, minute = _cutoff_hm(config)
    morning = announcement + timedelta(days=1)
    return datetime(morning.year, morning.month, morning.day, hour, minute, tzinfo=EASTERN)


def submission_window(announcement: date) -> tuple[datetime, datetime] | None:
    """The GMT window of submissions that Announcement releases, or None when arXiv releases
    nothing that evening (Friday and Saturday). From arXiv's availability schedule: the window
    runs 14:00 ET to 14:00 ET; Sunday's closes on Friday, Monday's opens on Friday."""
    weekday = announcement.weekday()  # Mon=0 .. Sun=6
    if weekday in (4, 5):
        return None
    end = announcement - timedelta(days=2) if weekday == 6 else announcement
    start = end - timedelta(days=3 if end.weekday() == 0 else 1)
    at_two = lambda d: datetime(d.year, d.month, d.day, 14, tzinfo=EASTERN).astimezone(timezone.utc)
    return at_two(start), at_two(end)
