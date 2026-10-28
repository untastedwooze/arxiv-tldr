from datetime import date
from pathlib import Path

import httpx

from arxiv_tldr.cli import main
from arxiv_tldr.config import Config
from arxiv_tldr.pipeline import run

from conftest import FakeMailer, combined_transport, ollama_handler, rss_handler

D = date(2026, 10, 26)
FEEDS = {"q-fin": "rss_q-fin.xml", "stat.ME": "rss_stat.ME.xml"}
SCORES = {
    "Volatility Forecasting with Rough Paths": (10, "Directly about volatility modelling."),
    "Heavy Tails in Crypto Returns": (9, "Tail estimation is a core interest."),
    "Robust Portfolio Selection via Optimal Transport": (7, "Adjacent optimal transport work."),
    "bootstrap": (4, "Generic statistics."),
}
OLLAMA_URL = "http://piglet.example:11434"


def setup(tmp_path, **overrides):
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
    ollama_requests = []
    client = httpx.Client(
        transport=combined_transport(
            rss_handler(FEEDS), ollama_handler(SCORES, ollama_requests)
        )
    )
    return config, client, FakeMailer(), ollama_requests


def test_run_sends_digest_of_featured_papers_by_score(tmp_path, clock):
    config, client, mailer, _ = setup(tmp_path)
    run(D, config=config, client=client, mailer=mailer, clock=clock)

    assert len(mailer.sent) == 1
    msg = mailer.sent[0]
    assert msg.recipients == ["reader@example.com"]
    assert msg.subject == "arxiv-tldr · Mon 2026-10-26 · 3 featured / 0 overflow / 4 triaged"
    html = msg.html
    positions = [
        html.index(t)
        for t in (
            "Volatility Forecasting with Rough Paths",
            "Heavy Tails in Crypto Returns",
            "Robust Portfolio Selection via Optimal Transport",
        )
    ]
    assert positions == sorted(positions)
    assert "bootstrap" not in html
    assert "Why you&#39;re seeing this:" in html or "Why you're seeing this:" in html
    assert "Directly about volatility modelling." in html
    assert "Rough paths forecast volatility." in html  # Summary replaces the abstract
    assert "Alice Smith, Bob Jones, Carol Lee et al." in html
    assert "q-fin.ST" in html and "2610.00001" in html
    assert 'href="https://arxiv.org/abs/2610.00001"' in html
    assert 'href="https://arxiv.org/html/2610.00001"' in html
    assert 'href="https://arxiv.org/pdf/2610.00001"' in html
    assert "math.OC" in html and "q-fin.PM" in html
    assert "Directly about volatility modelling." in msg.text


def test_cap_limits_featured_papers(tmp_path, clock):
    config, client, mailer, _ = setup(tmp_path, cap=1)
    run(D, config=config, client=client, mailer=mailer, clock=clock)
    msg = mailer.sent[0]
    assert "1 featured / 2 overflow / 4 triaged" in msg.subject
    assert "Volatility Forecasting with Rough Paths" in msg.html
    # past the cap: title-only link, no Rationale
    assert "Heavy Tails in Crypto Returns" in msg.html
    assert "Tail estimation is a core interest." not in msg.html


def test_threshold_is_configurable(tmp_path, clock):
    config, client, mailer, _ = setup(tmp_path, threshold=10)
    run(D, config=config, client=client, mailer=mailer, clock=clock)
    assert "1 featured / 0 overflow / 4 triaged" in mailer.sent[0].subject


def test_triage_prompt_starts_with_interest_profile_and_asks_json_schema(tmp_path, clock):
    config, client, mailer, requests = setup(tmp_path)
    run(D, config=config, client=client, mailer=mailer, clock=clock)
    requests = [r for r in requests if "score" in r["format"]["properties"]]
    assert len(requests) == 4
    for body in requests:
        assert body["prompt"].startswith("I care about volatility and tail risk.")
        assert body["stream"] is False
        assert body["format"]["properties"].keys() >= {"rationale", "score"}
        assert body["options"]["temperature"] <= 0.2
        assert body["model"] == config.ollama_model


def test_rerun_does_not_retriage_or_resend(tmp_path, clock):
    config, client, mailer, requests = setup(tmp_path)
    run(D, config=config, client=client, mailer=mailer, clock=clock)
    run(D, config=config, client=client, mailer=mailer, clock=clock)
    assert len([r for r in requests if "score" in r["format"]["properties"]]) == 4
    assert len(mailer.sent) == 1


def test_cli_run_subcommand(tmp_path, clock, monkeypatch):
    config, client, mailer, _ = setup(tmp_path)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.toml").write_text(
        'watched_categories = ["q-fin", "stat.ME"]\ndb_path = "t.db"\n'
        f'interest_profile_path = "profile.md"\nollama_base_url = "{OLLAMA_URL}"\n'
        'recipients = ["reader@example.com"]\n'
    )
    assert main(["run", "2026-10-26"], client=client, clock=clock, mailer=mailer) == 0
    assert len(mailer.sent) == 1


def test_placeholder_interest_profile_ships_with_sections():
    text = (Path(__file__).parent.parent / "interest-profile.md").read_text()
    assert Config().interest_profile_path.name == "interest-profile.md"
    for heading in ("Core interests", "Adjacent interests", "Exclusions"):
        assert heading in text


def test_cli_run_defaults_to_todays_eastern_announcement_date(tmp_path, monkeypatch):
    from datetime import datetime, timezone

    config, client, mailer, _ = setup(tmp_path)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.toml").write_text(
        'watched_categories = ["q-fin", "stat.ME"]\ndb_path = "t.db"\n'
        f'interest_profile_path = "profile.md"\nollama_base_url = "{OLLAMA_URL}"\n'
        'recipients = ["reader@example.com"]\n'
    )
    # 01:30 UTC on Oct 27 is 21:30 Monday evening in New York: Monday's Announcement.
    late = lambda: datetime(2026, 10, 27, 1, 30, tzinfo=timezone.utc)
    assert main(["run"], client=client, clock=late, mailer=mailer) == 0
    assert "Mon 2026-10-26" in mailer.sent[0].subject
