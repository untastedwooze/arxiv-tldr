import json
import smtplib
from datetime import date
from unittest.mock import MagicMock

import httpx

from arxiv_tldr.fulltext import extract_body
from arxiv_tldr.mailer import GmailMailer, Message
from arxiv_tldr.pipeline import run
from arxiv_tldr.store import Store

from conftest import combined_transport, ollama_handler, rss_handler
from test_failures import AFTER_CUTOFF, Time
from test_run import FEEDS, SCORES, setup

D = date(2026, 10, 26)


def test_a_400_for_one_paper_fails_that_paper_only(tmp_path, clock):
    config, _, mailer, _ = setup(tmp_path)
    inner = ollama_handler(SCORES)

    def bad_request(request):
        if request.url.host == "piglet.example" and "Heavy Tails" in json.loads(request.content)["prompt"]:
            return httpx.Response(400, json={"error": "prompt too long"})
        return inner(request)

    client = httpx.Client(transport=combined_transport(bad_request, rss_handler(FEEDS)))
    run(D, config=config, client=client, mailer=mailer, clock=clock)
    assert "2 featured" in mailer.sent[0].subject


def test_ollama_5xx_is_a_host_problem_that_is_retried(tmp_path):
    config, _, mailer, _ = setup(tmp_path)
    client = httpx.Client(transport=combined_transport(
        lambda r: httpx.Response(503) if r.url.host == "piglet.example" else None,
        rss_handler(FEEDS),
    ))
    t = Time(AFTER_CUTOFF)
    run(D, config=config, client=client, mailer=mailer, clock=t.clock, sleep=t.sleep)
    assert "featured" not in mailer.sent[0].subject and "503" in mailer.sent[0].text


def test_unbalanced_html_does_not_leave_a_skipped_region_open():
    html = (
        "<body><p>Intro text<nav><ul><li>menu<li>more</nav>"
        "<p>Results text<footer>foot</footer><p>Conclusion</body>"
    )
    text = extract_body(html)
    assert "Intro text" in text and "Results text" in text and "Conclusion" in text
    assert "menu" not in text and "foot" not in text


def test_a_zero_text_budget_falls_back_to_the_abstract(tmp_path, clock):
    config, client, mailer, _ = setup(tmp_path, num_ctx=1000)  # below the prompt reserve
    run(D, config=config, client=client, mailer=mailer, clock=clock)
    stored = Store(config.db_path).summaries(D)
    assert stored and all(s.source == "abstract" for s in stored.values())


def test_gmail_connection_has_a_timeout(monkeypatch):
    smtp_ssl = MagicMock()
    monkeypatch.setattr(smtplib, "SMTP_SSL", smtp_ssl)
    GmailMailer("me@gmail.com", "pw").send(Message("S", "<p>h</p>", "t", ["a@x.org"]))
    assert smtp_ssl.call_args.kwargs.get("timeout")
