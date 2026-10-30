import json
from datetime import datetime, timedelta, timezone

import httpx

from arxiv_tldr.pipeline import run
from arxiv_tldr.store import Store

from conftest import FakeMailer, combined_transport, ollama_handler, rss_handler
from test_run import D, FEEDS, SCORES, setup


def test_overflow_header_footer_and_plain_text(tmp_path):
    start = datetime(2026, 10, 26, 1, 0, tzinfo=timezone.utc)
    ticks = iter(start + timedelta(seconds=75 * i) for i in range(100))
    config, client, mailer, _ = setup(tmp_path, cap=1)
    run(D, config=config, client=client, mailer=mailer, clock=lambda: next(ticks))
    msg = mailer.sent[0]
    assert msg.subject == "arxiv-tldr · Mon 2026-10-26 · 1 featured / 2 overflow / 4 triaged"
    assert msg.text.index("[9]") < msg.text.index("[7]")
    assert msg.html.index('id="o9"') < msg.html.index('id="o7"')  # one group per score
    for body in (msg.html, msg.text):
        assert "Overflow" in body
        assert "Mon 2026-10-26" in body
        assert "Failures: 0" in body and config.ollama_model in body
    assert msg.html.count("Heavy Tails in Crypto Returns") == 1
    assert msg.text.count("Volatility Forecasting with Rough Paths") == 1
    assert "Robust Portfolio Selection via Optimal Transport" in msg.text
    assert "https://arxiv.org/abs/" in msg.text
    assert "Run time: 1m 15s" in msg.text and "Run time: 1m 15s" in msg.html


def test_untriageable_candidate_counts_as_failure_and_timings_are_stored(tmp_path, clock):
    config, _, mailer, _ = setup(tmp_path)

    def bad(request):
        if request.url.host == "piglet.example":
            body = json.loads(request.content)
            if "bootstrap" in body["prompt"]:
                return httpx.Response(200, json={"response": "not json", "done": True})
        return None

    client = httpx.Client(
        transport=combined_transport(bad, rss_handler(FEEDS), ollama_handler(SCORES))
    )
    run(D, config=config, client=client, mailer=mailer, clock=clock)
    msg = mailer.sent[0]
    assert "3 triaged" in msg.subject
    assert "Failures: 1" in msg.text and "Failures: 1" in msg.html
    timings = Store(config.db_path).call_timings(D)
    assert [t.kind for t in timings] == ["triage"] * 3 + ["summary"] * 3
    assert all(t.seconds >= 0 for t in timings)
