import json
import logging
from datetime import date, datetime, timedelta, timezone

import httpx

from arxiv_tldr.pipeline import run
from arxiv_tldr.store import Store

from conftest import combined_transport, ollama_handler, rss_handler
from test_run import FEEDS, SCORES, setup

D = date(2026, 10, 26)
BEFORE_CUTOFF = datetime(2026, 10, 27, 1, 0, tzinfo=timezone.utc)  # 21:00 ET on the 26th
AFTER_CUTOFF = datetime(2026, 10, 27, 10, 0, tzinfo=timezone.utc)  # 06:00 ET on the 27th


class Time:
    """A clock and a sleep that share one timeline, so waiting moves the clock."""

    def __init__(self, now):
        self.now = now
        self.slept = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += timedelta(seconds=seconds)


def down(request):
    if request.url.host == "piglet.example":
        raise httpx.ConnectError("piglet is off")


def test_unreachable_past_cutoff_sends_failure_notice_and_no_digest(tmp_path):
    config, _, mailer, _ = setup(tmp_path)
    client = httpx.Client(transport=combined_transport(down, rss_handler(FEEDS)))
    t = Time(AFTER_CUTOFF)
    run(D, config=config, client=client, mailer=mailer, clock=t.clock, sleep=t.sleep)

    assert len(mailer.sent) == 1
    notice = mailer.sent[0]
    assert notice.recipients == ["reader@example.com"]
    assert "2026-10-26" in notice.subject and "arxiv-tldr" in notice.subject
    assert "featured" not in notice.subject
    assert "unreachable" in notice.text and "unreachable" in notice.html
    assert t.slept == []
    assert "unreachable" in Store(config.db_path).failure_notice(D)


def test_unreachable_before_cutoff_retries_until_it_recovers(tmp_path):
    config, _, mailer, _ = setup(tmp_path)
    t = Time(BEFORE_CUTOFF)
    state = {"up": False}
    ollama = ollama_handler(SCORES)

    def flaky(request):
        return ollama(request) if state["up"] else down(request)

    def sleep(seconds):
        t.sleep(seconds)
        state["up"] = len(t.slept) >= 2

    client = httpx.Client(transport=combined_transport(flaky, rss_handler(FEEDS)))
    run(D, config=config, client=client, mailer=mailer, clock=t.clock, sleep=sleep)

    assert t.slept == [1200, 1200]
    assert len(mailer.sent) == 1 and "3 featured" in mailer.sent[0].subject
    assert Store(config.db_path).failure_notice(D) is None


def test_keeps_retrying_then_gives_up_at_the_cutoff(tmp_path):
    config, _, mailer, _ = setup(tmp_path)
    client = httpx.Client(transport=combined_transport(down, rss_handler(FEEDS)))
    t = Time(BEFORE_CUTOFF)  # 01:00 UTC, cutoff 08:00 UTC: 21 retries of 20 minutes
    run(D, config=config, client=client, mailer=mailer, clock=t.clock, sleep=t.sleep)
    assert len(t.slept) == 21
    assert len(mailer.sent) == 1 and "featured" not in mailer.sent[0].subject


def test_failing_feeds_are_retried_and_reported(tmp_path):
    config, _, mailer, _ = setup(tmp_path)
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    t = Time(AFTER_CUTOFF)
    run(D, config=config, client=client, mailer=mailer, clock=t.clock, sleep=t.sleep)
    assert len(mailer.sent) == 1 and "503" in mailer.sent[0].text


def test_malformed_feed_is_a_failure_not_a_crash(tmp_path):
    config, _, mailer, _ = setup(tmp_path)
    junk = (
        "<rss xmlns:arxiv=\"http://arxiv.org/schemas/atom\" version=\"2.0\"><channel><item>"
        "<title>x</title><description>garbage</description>"
        "<arxiv:announce_type>new</arxiv:announce_type></item></channel></rss>"
    )
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=junk)))
    t = Time(AFTER_CUTOFF)
    run(D, config=config, client=client, mailer=mailer, clock=t.clock, sleep=t.sleep)
    assert len(mailer.sent) == 1 and "featured" not in mailer.sent[0].subject


def test_empty_feeds_send_nothing_and_record_no_failure(tmp_path):
    config, _, mailer, _ = setup(tmp_path)
    empty = '<rss version="2.0"><channel><title>q-fin</title></channel></rss>'
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=empty)))
    t = Time(BEFORE_CUTOFF)
    run(D, config=config, client=client, mailer=mailer, clock=t.clock, sleep=t.sleep)
    assert mailer.sent == [] and t.slept == []
    assert Store(config.db_path).failure_notice(D) is None


def test_one_papers_malformed_output_does_not_stop_the_digest(tmp_path, clock):
    config, _, mailer, _ = setup(tmp_path)
    inner = ollama_handler(SCORES)

    def garbled(request):
        if request.url.host == "piglet.example" and "Heavy Tails" in json.loads(request.content)["prompt"]:
            return httpx.Response(200, json={"response": "not json", "done": True})
        return inner(request)

    client = httpx.Client(transport=combined_transport(garbled, rss_handler(FEEDS)))
    run(D, config=config, client=client, mailer=mailer, clock=clock)
    assert len(mailer.sent) == 1
    msg = mailer.sent[0]
    assert "2 featured" in msg.subject
    assert "Volatility Forecasting with Rough Paths" in msg.html
    assert "Heavy Tails in Crypto Returns" not in msg.html


def test_rejected_send_is_logged_and_the_digest_stays_unsent(tmp_path, clock, caplog):
    config, client, mailer, _ = setup(tmp_path)

    class Rejecting:
        def send(self, message):
            raise RuntimeError("Gmail rejected the message")

    with caplog.at_level(logging.ERROR):
        t = Time(AFTER_CUTOFF)
        run(D, config=config, client=client, mailer=Rejecting(), clock=t.clock, sleep=t.sleep)
    assert "Gmail rejected the message" in caplog.text
    assert not Store(config.db_path).digest_sent(D)
    run(D, config=config, client=client, mailer=mailer, clock=t.clock)
    assert len(mailer.sent) == 1


def test_rejected_digest_is_retried_until_the_cutoff(tmp_path):
    config, client, mailer, requests = setup(tmp_path)
    t = Time(BEFORE_CUTOFF)
    state = {"rejecting": True}

    class Flaky:
        def send(self, message):
            if state["rejecting"]:
                raise RuntimeError("Gmail rejected the message")
            mailer.send(message)

    def sleep(seconds):
        t.sleep(seconds)
        state["rejecting"] = len(t.slept) < 2

    run(D, config=config, client=client, mailer=Flaky(), clock=t.clock, sleep=sleep)
    assert t.slept == [1200, 1200]
    assert len(mailer.sent) == 1 and "3 featured" in mailer.sent[0].subject
    assert len(requests) == 4 + 3  # only the send was retried
