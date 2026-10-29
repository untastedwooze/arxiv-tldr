import json
from datetime import date, datetime, timezone

import httpx

from arxiv_tldr.cli import main
from arxiv_tldr.pipeline import run

from conftest import combined_transport, ollama_handler, rss_handler
from test_failures import AFTER_CUTOFF, BEFORE_CUTOFF, Time
from test_run import FEEDS, OLLAMA_URL, SCORES, setup

D = date(2026, 10, 26)


def test_paper_whose_summary_stays_malformed_is_listed_with_its_abstract_and_a_note(
    tmp_path, clock
):
    config, _, mailer, _ = setup(tmp_path)
    inner = ollama_handler(SCORES)

    def garbled(request):
        body = json.loads(request.content) if request.url.host == "piglet.example" else {}
        if "tldr" in body.get("format", {}).get("properties", {}) and "Heavy Tails" in body["prompt"]:
            return httpx.Response(200, json={"response": "not json", "done": True})
        return inner(request)

    client = httpx.Client(transport=combined_transport(garbled, rss_handler(FEEDS)))
    run(D, config=config, client=client, mailer=mailer, clock=clock)
    msg = mailer.sent[0]
    assert "3 featured" in msg.subject
    assert "A study of tail behaviour" in msg.html
    assert "Summary unavailable" in msg.html and "Summary unavailable" in msg.text


def cli_setup(tmp_path, monkeypatch, recipients='["reader@example.com"]'):
    config, client, mailer, requests = setup(tmp_path)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.toml").write_text(
        'watched_categories = ["q-fin", "stat.ME"]\ndb_path = "t.db"\n'
        f'interest_profile_path = "profile.md"\nollama_base_url = "{OLLAMA_URL}"\n'
        f"recipients = {recipients}\n"
    )
    return client, mailer, requests


def test_cli_run_after_midnight_eastern_resolves_the_previous_announcement(tmp_path, monkeypatch):
    client, mailer, _ = cli_setup(tmp_path, monkeypatch)
    # 06:30 UTC on Oct 27 is 02:30 Tuesday in New York, before the 04:00 cutoff: Monday's.
    catch_up = lambda: datetime(2026, 10, 27, 6, 30, tzinfo=timezone.utc)
    assert main(["run"], client=client, clock=catch_up, mailer=mailer) == 0
    assert "Mon 2026-10-26" in mailer.sent[0].subject


def test_cli_run_after_the_cutoff_resolves_todays_announcement(tmp_path, monkeypatch):
    client, mailer, _ = cli_setup(tmp_path, monkeypatch)
    fresh = rss_handler(FEEDS)

    def wed_listing(request):  # Tuesday's Announcement is the Wed 28 Oct listing
        response = fresh(request)
        if response is None or response.status_code != 200:
            return response
        return httpx.Response(200, text=response.text.replace("Tue, 27 Oct", "Wed, 28 Oct", 1))

    client = httpx.Client(transport=combined_transport(wed_listing, ollama_handler(SCORES)))
    morning = lambda: datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)  # 08:00 ET Tuesday
    assert main(["run"], client=client, clock=morning, mailer=mailer) == 0
    assert "Tue 2026-10-27" in mailer.sent[0].subject


def test_missing_recipients_fail_fast_before_any_llm_work(tmp_path, monkeypatch, clock, capsys):
    client, mailer, requests = cli_setup(tmp_path, monkeypatch, recipients="[]")
    assert main(["run", "2026-10-26"], client=client, clock=clock, mailer=mailer) == 2
    assert "ARXIV_TLDR_RECIPIENTS" in capsys.readouterr().err
    assert requests == [] and mailer.sent == []


def test_missing_gmail_credentials_fail_fast_when_no_mailer_is_injected(
    tmp_path, monkeypatch, clock, capsys
):
    client, _, requests = cli_setup(tmp_path, monkeypatch)
    for name in ("ARXIV_TLDR_GMAIL_ADDRESS", "ARXIV_TLDR_GMAIL_APP_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("arxiv_tldr.config.load_dotenv", lambda *a, **k: None)
    assert main(["send", "2026-10-26"], client=client, clock=clock) == 2
    assert "ARXIV_TLDR_GMAIL_APP_PASSWORD" in capsys.readouterr().err
    assert requests == []


def test_all_candidates_failing_triage_is_a_failure_not_an_empty_digest(tmp_path):
    config, _, mailer, _ = setup(tmp_path)

    def garbled(request):
        if request.url.host == "piglet.example":
            return httpx.Response(200, json={"response": "not json", "done": True})

    client = httpx.Client(transport=combined_transport(garbled, rss_handler(FEEDS)))
    t = Time(AFTER_CUTOFF)
    run(D, config=config, client=client, mailer=mailer, clock=t.clock, sleep=t.sleep)
    assert len(mailer.sent) == 1 and "featured" not in mailer.sent[0].subject
    assert "triaged" in mailer.sent[0].text


def test_later_step_failure_does_not_refetch_the_feeds(tmp_path):
    config, _, mailer, _ = setup(tmp_path)
    feed_requests = []
    state = {"up": False}
    ollama = ollama_handler(SCORES)

    def flaky(request):
        if request.url.host != "piglet.example":
            return None
        if state["up"]:
            return ollama(request)
        raise httpx.ConnectError("piglet is off")

    t = Time(BEFORE_CUTOFF)

    def sleep(seconds):
        t.sleep(seconds)
        state["up"] = True

    client = httpx.Client(transport=combined_transport(flaky, rss_handler(FEEDS, feed_requests)))
    run(D, config=config, client=client, mailer=mailer, clock=t.clock, sleep=sleep)
    assert len(mailer.sent) == 1 and sum(r.url.host == "rss.arxiv.org" for r in feed_requests) == len(FEEDS)
