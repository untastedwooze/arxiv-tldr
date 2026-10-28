from datetime import date

import httpx

from arxiv_tldr.config import Config
from arxiv_tldr.pipeline import run
from arxiv_tldr.store import Store

from conftest import (
    FakeMailer, combined_transport, html_handler, make_pdf, ollama_handler, pdf_handler,
    rss_handler,
)
from test_summaries import OLLAMA_URL, SCORES, summary_requests

D = date(2026, 10, 26)
TAIL_PDF = make_pdf(
    "Heavy Tails in Crypto Returns\nPDF-INTRO-TEXT we study tails.",
    "PDF-RESULTS-TEXT tails are heavy.\nReferences\n[1] PDF-REFERENCE-ENTRY",
)


def setup(tmp_path, pdfs, pages=None, **overrides):
    profile = tmp_path / "profile.md"
    profile.write_text("I care about volatility and tail risk.")
    config = Config(
        watched_categories=("q-fin", "stat.ME"), db_path=tmp_path / "t.db",
        interest_profile_path=profile, ollama_base_url=OLLAMA_URL,
        recipients=("reader@example.com",), **overrides,
    )
    requests = []
    pages = {"2610.00001": "html_2610.00001.html"} if pages is None else pages
    client = httpx.Client(transport=combined_transport(
        rss_handler({"q-fin": "rss_q-fin.xml", "stat.ME": "rss_stat.ME.xml"}),
        html_handler(pages), pdf_handler(pdfs), ollama_handler(SCORES, requests),
    ))
    return config, client, FakeMailer(), requests


def tail_prompt(requests):
    return next(r["prompt"] for r in summary_requests(requests) if "Heavy Tails" in r["prompt"])


def test_missing_html_falls_back_to_pdf_text(tmp_path, clock):
    config, client, mailer, requests = setup(tmp_path, {"2610.00002": TAIL_PDF})
    run(D, config=config, client=client, mailer=mailer, clock=clock)
    prompt = tail_prompt(requests)
    assert "PDF-INTRO-TEXT" in prompt and "PDF-RESULTS-TEXT" in prompt
    assert "PDF-REFERENCE-ENTRY" not in prompt
    msg = mailer.sent[0]
    assert "Abstract-only" not in msg.html and "Abstract-only" not in msg.text
    assert "Text cut" not in msg.html


def test_pdf_source_is_recorded(tmp_path, clock):
    config, client, mailer, _ = setup(tmp_path, {"2610.00002": TAIL_PDF})
    run(D, config=config, client=client, mailer=mailer, clock=clock)
    stored = Store(config.db_path).summaries(D)
    assert stored["2610.00002"].source == "pdf" and not stored["2610.00002"].cut
    assert stored["2610.00001"].source == "html"


def test_html_and_pdf_missing_gives_abstract_only(tmp_path, clock):
    config, client, mailer, requests = setup(tmp_path, {})
    run(D, config=config, client=client, mailer=mailer, clock=clock)
    assert "A study of tail behaviour & estimation." in tail_prompt(requests)
    assert "Abstract-only" in mailer.sent[0].html


def test_corrupt_pdf_gives_abstract_only(tmp_path, clock):
    config, client, mailer, _ = setup(tmp_path, {"2610.00002": b"not a pdf"})
    run(D, config=config, client=client, mailer=mailer, clock=clock)
    assert "Abstract-only" in mailer.sent[0].html


def test_overlong_text_is_cut_to_budget_and_marked(tmp_path, clock):
    long_pdf = make_pdf("START-MARK " + "word " * 40, "END-MARK")
    config, client, mailer, requests = setup(
        tmp_path, {"2610.00002": long_pdf}, summary_text_budget=60
    )
    run(D, config=config, client=client, mailer=mailer, clock=clock)
    prompt = tail_prompt(requests)
    assert "START-MARK" in prompt and "END-MARK" not in prompt
    body = prompt.split("Full text:\n", 1)[1]
    assert len(body.strip()) <= 60
    msg = mailer.sent[0]
    split = msg.html.index("Heavy Tails in Crypto Returns")
    assert "Text cut" in msg.html[split:] and "Text cut" in msg.text  # HTML paper cut too
    assert Store(config.db_path).summaries(D)["2610.00002"].cut


def test_default_budget_is_derived_from_num_ctx():
    assert Config(num_ctx=8000).text_budget_chars < Config(num_ctx=32768).text_budget_chars
    assert Config(summary_text_budget=99).text_budget_chars == 99
