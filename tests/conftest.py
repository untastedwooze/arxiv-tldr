from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def rss_transport(feeds: dict[str, str], requests: list | None = None) -> httpx.MockTransport:
    """Serve saved RSS fixtures at rss.arxiv.org/rss/<category>."""

    def handler(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(request)
        prefix = "/rss/"
        if request.url.host == "rss.arxiv.org" and request.url.path.startswith(prefix):
            name = request.url.path[len(prefix):]
            if name in feeds:
                return httpx.Response(200, text=(FIXTURES / feeds[name]).read_text())
        return httpx.Response(404)

    return httpx.MockTransport(handler)


@pytest.fixture
def clock():
    return lambda: datetime(2026, 10, 26, 1, 0, tzinfo=timezone.utc)
