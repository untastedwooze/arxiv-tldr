from datetime import date

import httpx
import pytest

from arxiv_tldr.config import Config
from arxiv_tldr.pipeline import run

from test_failures import AFTER_CUTOFF, Time
from conftest import (
    FakeMailer, SUMMARY_FIELDS, combined_transport, html_handler, ollama_handler, rss_handler,
)

D = date(2026, 10, 26)
SCORES = {
    "Volatility Forecasting with Rough Paths": (10, "Directly about volatility modelling."),
    "Heavy Tails in Crypto Returns": (9, "Tail estimation is a core interest."),
    "Robust Portfolio Selection via Optimal Transport": (3, "Not relevant."),
    "bootstrap": (4, "Generic statistics."),
}
OLLAMA_URL = "http://piglet.example:11434"
TAIL_SUMMARY = {**SUMMARY_FIELDS, "tldr": "Tails are heavier than assumed."}


def setup(tmp_path, pages=None, **overrides):
    profile = tmp_path / "profile.md"
    profile.write_text("I care about volatility and tail risk.")
    config = Config(
        watched_categories=("q-fin", "stat.ME"),
        db_path=tmp_path / "t.db",
        interest_profile_path=profile,
        ollama_base_url=OLLAMA_URL,
        recipients=("reader@example.com",),
        **overrides,
    )
    requests = []
    feeds = {"q-fin": "rss_q-fin.xml", "stat.ME": "rss_stat.ME.xml"}
    pages = {"2610.00001": "html_2610.00001.html"} if pages is None else pages
    client = httpx.Client(
        transport=combined_transport(
            rss_handler(feeds),
            html_handler(pages),
            ollama_handler(SCORES, requests, {"Heavy Tails": TAIL_SUMMARY}),
        )
    )
    return config, client, FakeMailer(), requests


def summary_requests(requests):
    return [r for r in requests if "tldr" in r["format"]["properties"]]


def test_digest_shows_labelled_summary_fields_from_html(tmp_path, clock):
    config, client, mailer, _ = setup(tmp_path)
    run(D, config=config, client=client, mailer=mailer, clock=clock)
    msg = mailer.sent[0]
    for label in (
        "TL;DR", "Problem", "Method", "Data", "Key results", "Limitations / caveats",
        "Why it matters to you",
    ):
        assert label in msg.html and label in msg.text
    assert "Rough paths forecast volatility." in msg.html
    assert "12% lower error." in msg.text
    assert "Directly about volatility modelling." in msg.html  # Rationale kept
    # Summary replaces the raw abstract
    assert "We forecast volatility using rough path signatures." not in msg.html


def test_summary_prompt_uses_body_without_references_or_appendices(tmp_path, clock):
    config, client, mailer, requests = setup(tmp_path)
    run(D, config=config, client=client, mailer=mailer, clock=clock)
    prompt = next(
        r["prompt"] for r in summary_requests(requests)
        if "Volatility Forecasting with Rough Paths" in r["prompt"]
    )
    assert "INTRO-BODY-TEXT" in prompt and "RESULTS-BODY-TEXT" in prompt
    assert "REFERENCE-ENTRY-TEXT" not in prompt
    assert "APPENDIX-BODY-TEXT" not in prompt
    assert "SCRIPTJUNK" not in prompt
    assert prompt.startswith("I care about volatility and tail risk.")


def test_every_summary_call_sets_num_ctx_from_config(tmp_path, clock):
    config, client, mailer, requests = setup(tmp_path, num_ctx=12345)
    run(D, config=config, client=client, mailer=mailer, clock=clock)
    calls = summary_requests(requests)
    assert len(calls) == 2  # two Featured Papers
    assert all(r["options"]["num_ctx"] == 12345 for r in calls)
    assert Config().num_ctx == 32768


def test_missing_html_gives_marked_abstract_only_summary(tmp_path, clock):
    config, client, mailer, requests = setup(tmp_path)
    run(D, config=config, client=client, mailer=mailer, clock=clock)
    msg = mailer.sent[0]
    tail_html = msg.html[msg.html.index("Heavy Tails in Crypto Returns"):]
    assert "Abstract-only" in tail_html
    assert "Tails are heavier than assumed." in tail_html
    # the paper with HTML is not marked
    vol_html = msg.html[: msg.html.index("Heavy Tails in Crypto Returns")]
    assert "Abstract-only" not in vol_html
    assert "Abstract-only" in msg.text
    prompt = next(
        r["prompt"] for r in summary_requests(requests) if "Heavy Tails" in r["prompt"]
    )
    assert "A study of tail behaviour & estimation." in prompt


def test_rerun_after_failed_send_does_not_resummarize(tmp_path, clock):
    config, client, mailer, requests = setup(tmp_path)

    class Flaky(FakeMailer):
        def send(self, message):
            raise RuntimeError("smtp down")

    t = Time(AFTER_CUTOFF)  # retried to the cutoff; the rejection is logged, not raised
    run(D, config=config, client=client, mailer=Flaky(), clock=t.clock, sleep=t.sleep)
    assert len(summary_requests(requests)) == 2
    run(D, config=config, client=client, mailer=mailer, clock=t.clock)
    assert len(summary_requests(requests)) == 2
    assert "Rough paths forecast volatility." in mailer.sent[0].html
