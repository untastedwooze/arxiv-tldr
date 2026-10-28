import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def rss_handler(feeds: dict[str, str], requests: list | None = None):
    """Serve saved RSS fixtures at rss.arxiv.org/rss/<category>."""

    def handler(request: httpx.Request) -> httpx.Response | None:
        if requests is not None:
            requests.append(request)
        prefix = "/rss/"
        if request.url.host == "rss.arxiv.org" and request.url.path.startswith(prefix):
            name = request.url.path[len(prefix):]
            if name in feeds:
                return httpx.Response(200, text=(FIXTURES / feeds[name]).read_text())
            return httpx.Response(404)
        return None

    return handler


def rss_transport(feeds: dict[str, str], requests: list | None = None) -> httpx.MockTransport:
    handler = rss_handler(feeds, requests)
    return httpx.MockTransport(lambda r: handler(r) or httpx.Response(404))


def ollama_handler(scores: dict[str, tuple[int, str]], requests: list | None = None):
    """Canned Ollama: reply to a Triage prompt by the title it mentions."""

    def handler(request: httpx.Request) -> httpx.Response | None:
        if request.url.host != "piglet.example" or request.url.path != "/api/generate":
            return None
        body = json.loads(request.content)
        if requests is not None:
            requests.append(body)
        for title, (score, rationale) in scores.items():
            if title in body["prompt"]:
                answer = {"rationale": rationale, "score": score}
                return httpx.Response(200, json={"response": json.dumps(answer), "done": True})
        return httpx.Response(500)

    return handler


def combined_transport(*handlers) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        for h in handlers:
            response = h(request)
            if response is not None:
                return response
        return httpx.Response(404)

    return httpx.MockTransport(handler)


class FakeMailer:
    """Records the messages it is asked to send."""

    def __init__(self):
        self.sent = []

    def send(self, message) -> None:
        self.sent.append(message)


@pytest.fixture
def clock():
    return lambda: datetime(2026, 10, 26, 1, 0, tzinfo=timezone.utc)
