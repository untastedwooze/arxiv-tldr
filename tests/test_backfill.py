from datetime import date, datetime, timedelta, timezone

import httpx
import pytest

from arxiv_tldr.cli import main
from arxiv_tldr.cli import main
from arxiv_tldr.config import Config
from arxiv_tldr.feed import FeedError, fetch
from arxiv_tldr.pipeline import run
from arxiv_tldr.store import Store

from conftest import (
    FIXTURES, FakeMailer, api_handler, catchup_handler, combined_transport, ollama_handler, rss_handler,
)

D = date(2026, 10, 26)  # Monday evening; arXiv labels the release Tue 2026-10-27
# 21:00 ET on Tue 27 Oct: the current Announcement is the 27th, so the 26th is a past one.
NOW = datetime(2026, 10, 28, 1, 0, tzinfo=timezone.utc)
OLLAMA_URL = "http://piglet.example:11434"
CATCHUP = {
    ("q-fin", "2026-10-27"): "catchup_q-fin.html",
    ("stat.ME", "2026-10-27"): "catchup_stat.ME.html",
}
SCORES = {
    "Volatility Forecasting with Rough Paths": (10, "Directly about volatility modelling."),
    "Heavy Tails in Crypto Returns": (9, "Tail estimation is a core interest."),
    "Robust Portfolio Selection via Optimal Transport": (7, "Adjacent optimal transport work."),
    "bootstrap": (4, "Generic statistics."),
}


def clock():
    return NOW


class Sleeps:
    def __init__(self):
        self.calls = []

    def __call__(self, seconds):
        self.calls.append(seconds)


def setup(tmp_path, *handlers, **overrides):
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
    client = httpx.Client(transport=combined_transport(*handlers))
    return config, client, FakeMailer()


def test_past_date_in_catchup_range_sends_a_late_digest_of_catchups_new_and_cross_papers(tmp_path):
    requests = []
    config, client, mailer = setup(
        tmp_path, catchup_handler(CATCHUP, requests), ollama_handler(SCORES)
    )
    run(D, config=config, client=client, mailer=mailer, clock=clock, sleep=Sleeps())

    assert [r.url.path for r in requests] == [
        "/catchup/q-fin/2026-10-27", "/catchup/stat.ME/2026-10-27",
    ]
    stored = {c.arxiv_id: c for c in Store(config.db_path).candidates(D)}
    # replacements are excluded; the paper in two Watched Categories is one "new" Candidate
    assert sorted(stored) == ["2610.00001", "2610.00002", "2610.00004", "2610.00005"]
    assert stored["2610.00002"].announce_type == "new"
    assert stored["2610.00004"].announce_type == "cross"
    assert stored["2610.00004"].primary_category == "math.OC"
    assert stored["2610.00004"].cross_list_categories == ["q-fin.PM"]
    assert stored["2610.00001"].authors == ["Alice Smith", "Bob Jones", "Carol Lee", "Dan Wu"]
    assert stored["2610.00002"].abstract == "A study of tail behaviour & estimation."

    (message,) = mailer.sent
    assert message.subject == (
        "arxiv-tldr · Late Digest for Mon 2026-10-26 · 3 featured / 0 overflow / 4 triaged"
    )
    assert "Late Digest for Mon 2026-10-26" in message.html
    assert "Late Digest for Mon 2026-10-26" in message.text
    assert "inferred" not in message.html  # a catchup backfill is exact


def cli(tmp_path, monkeypatch, *handlers):
    config, client, mailer = setup(tmp_path, *handlers)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.toml").write_text(
        'watched_categories = ["q-fin", "stat.ME"]\ndb_path = "t.db"\n'
        f'interest_profile_path = "profile.md"\nollama_base_url = "{OLLAMA_URL}"\n'
        'recipients = ["reader@example.com"]\n'
    )

    def call(*argv):
        sleeps = Sleeps()
        code = main(list(argv), client=client, clock=clock, mailer=mailer, sleep=sleeps)
        return code, sleeps

    return call, mailer, config


def test_cli_run_with_a_past_date_backfills(tmp_path, monkeypatch):
    call, mailer, _ = cli(tmp_path, monkeypatch, catchup_handler(CATCHUP), ollama_handler(SCORES))
    code, _ = call("run", "2026-10-26")
    assert code == 0
    assert "Late Digest for Mon 2026-10-26" in mailer.sent[0].subject


def test_cli_run_with_a_future_date_is_refused(tmp_path, monkeypatch, capsys):
    call, mailer, config = cli(tmp_path, monkeypatch, rss_handler({}), ollama_handler(SCORES))
    code, sleeps = call("run", "2026-10-28")
    assert code != 0
    assert "2026-10-28" in capsys.readouterr().err
    assert mailer.sent == [] and sleeps.calls == []
    assert Store(config.db_path).candidates(date(2026, 10, 28)) == []


def test_cli_backfill_failure_exits_nonzero_with_the_reason_and_no_failure_notice(
    tmp_path, monkeypatch, capsys
):
    def unreachable(request):
        if request.url.host == "piglet.example":
            raise httpx.ConnectError("piglet is off")

    call, mailer, config = cli(tmp_path, monkeypatch, unreachable, catchup_handler(CATCHUP))
    code, sleeps = call("run", "2026-10-26")

    assert code == 1
    err = capsys.readouterr().err
    assert err.startswith("arxiv-tldr: ") and "unreachable" in err
    assert mailer.sent == []  # no Failure Notice, no Digest
    assert Store(config.db_path).failure_notice(D) is None
    assert sleeps.calls == [15]  # only the catchup crawl-delay: no retry sleeps


def test_cli_backfill_with_catchup_unreachable_exits_nonzero(tmp_path, monkeypatch, capsys):
    def down(request):
        if request.url.host == "arxiv.org":
            raise httpx.ConnectError("no route")

    call, mailer, _ = cli(tmp_path, monkeypatch, down, ollama_handler(SCORES))
    code, sleeps = call("run", "2026-10-26")
    assert code == 1 and mailer.sent == [] and sleeps.calls == []
    assert capsys.readouterr().err.startswith("arxiv-tldr: ")


def test_cli_backfill_with_ollama_500_exits_nonzero(tmp_path, monkeypatch, capsys):
    call, mailer, _ = cli(tmp_path, monkeypatch, catchup_handler(CATCHUP), ollama_handler({}))
    code, sleeps = call("run", "2026-10-26")
    assert code == 1 and mailer.sent == []
    assert "Ollama" in capsys.readouterr().err


def test_cli_fetch_with_a_past_date_uses_catchup(tmp_path, monkeypatch, capsys):
    call, _, config = cli(tmp_path, monkeypatch, catchup_handler(CATCHUP))
    code, sleeps = call("fetch", "2026-10-26")
    assert code == 0 and sleeps.calls == [15]
    assert len(Store(config.db_path).candidates(D)) == 4
    assert "4 candidates" in capsys.readouterr().out


API = {"q-fin": "api_q-fin.xml", "stat.ME": "api_q-fin.xml"}
NOT_IN_CATCHUP = {("q-fin", "2026-10-27"): 400, ("stat.ME", "2026-10-27"): 400}


def test_catchup_400_reconstructs_from_the_api_and_the_late_digest_says_so(tmp_path):
    api_requests = []
    config, client, mailer = setup(
        tmp_path, catchup_handler(NOT_IN_CATCHUP), api_handler(API, api_requests),
        ollama_handler(SCORES),
    )
    sleeps = Sleeps()
    run(D, config=config, client=client, mailer=mailer, clock=clock, sleep=sleeps)

    # Monday evening's window is Fri 14:00 ET to Mon 14:00 ET, in GMT (EDT is UTC-4)
    queries = [r.url.params["search_query"] for r in api_requests]
    assert queries == [
        "cat:q-fin* AND submittedDate:[202610231800 TO 202610261800]",
        "cat:stat.ME AND submittedDate:[202610231800 TO 202610261800]",
    ]
    assert sleeps.calls == [3]  # the API terms: spaced requests

    by_id = {c.arxiv_id: c for c in Store(config.db_path).candidates(D)}
    assert sorted(by_id) == ["2610.00001", "2610.00004", "2610.00005"]
    assert by_id["2610.00001"].announce_type == "new"  # primary in a Watched Category
    assert by_id["2610.00005"].announce_type == "new"
    assert by_id["2610.00004"].announce_type == "cross"
    assert by_id["2610.00001"].title == "Volatility Forecasting with Rough Paths"
    assert by_id["2610.00001"].abstract == "We forecast volatility using rough path signatures."
    assert by_id["2610.00001"].authors == ["Alice Smith", "Bob Jones"]
    assert by_id["2610.00004"].cross_list_categories == ["q-fin.PM"]

    (message,) = mailer.sent
    assert "Late Digest for Mon 2026-10-26" in message.subject
    for body in (message.html, message.text):
        assert "inferred from submission dates" in body
        assert "may be missing" in body


@pytest.mark.parametrize("evening, window", [
    (date(2026, 10, 25), "202610221800 TO 202610231800"),  # Sun: Thu 14:00 - Fri 14:00 ET
    (date(2026, 10, 27), "202610261800 TO 202610271800"),  # Tue: Mon 14:00 - Tue 14:00 ET
])
def test_reconstruction_window_follows_the_weekday_schedule(tmp_path, evening, window):
    api_requests = []
    listing = (evening + timedelta(days=1)).isoformat()
    config, client, _ = setup(
        tmp_path, catchup_handler({("q-fin", listing): 400}), api_handler(API, api_requests),
    )
    later = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
    fetch(evening, config=config, client=client, store=Store(config.db_path),
          clock=lambda: later, sleep=Sleeps())
    assert window in api_requests[0].url.params["search_query"]


def test_friday_evening_has_no_announcement_to_reconstruct(tmp_path):
    api_requests = []
    config, client, mailer = setup(
        tmp_path, catchup_handler({("q-fin", "2026-10-24"): 400}), api_handler(API, api_requests),
        ollama_handler(SCORES),
    )
    run(date(2026, 10, 23), config=config, client=client, mailer=mailer, clock=clock,
        sleep=Sleeps())
    assert api_requests == [] and mailer.sent == []


def test_friday_evening_empty_catchup_page_sends_nothing(tmp_path):
    config, client, mailer = setup(
        tmp_path,
        catchup_handler({("q-fin", "2026-10-24"): "catchup_empty.html",
                         ("stat.ME", "2026-10-24"): "catchup_empty.html"}),
        ollama_handler(SCORES),
    )
    run(date(2026, 10, 23), config=config, client=client, mailer=mailer, clock=clock,
        sleep=Sleeps())
    assert mailer.sent == [] and Store(config.db_path).candidates(date(2026, 10, 23)) == []


def test_backfill_goes_ahead_despite_a_stored_failure_notice_and_a_sent_digest(tmp_path):
    config, client, mailer = setup(tmp_path, catchup_handler(CATCHUP), ollama_handler(SCORES))
    store = Store(config.db_path)
    store.record_failure_notice(D, reason="piglet was off", sent_at=NOW)
    run(D, config=config, client=client, mailer=mailer, clock=clock, store=store, sleep=Sleeps())
    assert len(mailer.sent) == 1
    assert store.digest_sent(D)

    run(D, config=config, client=client, mailer=mailer, clock=clock, store=store, sleep=Sleeps())
    assert len(mailer.sent) == 2  # a deliberate resend


def test_backfill_reuses_stored_candidates_and_triage_results(tmp_path):
    ollama, requests = [], []
    config, client, mailer = setup(
        tmp_path, catchup_handler(CATCHUP, requests), ollama_handler(SCORES, ollama)
    )
    run(D, config=config, client=client, mailer=mailer, clock=clock, sleep=Sleeps())
    calls, fetches = len(ollama), len(requests)
    run(D, config=config, client=client, mailer=mailer, clock=clock, sleep=Sleeps())
    assert len(ollama) == calls and len(requests) == fetches
    assert len(mailer.sent) == 2


def test_catchup_pages_are_spaced_by_the_crawl_delay(tmp_path):
    config, client, mailer = setup(tmp_path, catchup_handler(CATCHUP), ollama_handler(SCORES))
    sleeps = Sleeps()
    run(D, config=config, client=client, mailer=mailer, clock=clock, sleep=sleeps)
    assert sleeps.calls == [15]


def test_a_malformed_catchup_page_is_a_feed_error_and_stores_nothing(tmp_path):
    config, client, _ = setup(tmp_path)
    # an entry count that disagrees with the page's own totals
    page = (FIXTURES / "catchup_q-fin.html").read_text().replace(
        "showing 2 of 2 entries", "showing 3 of 3 entries"
    )
    client = httpx.Client(transport=combined_transport(
        lambda r: httpx.Response(200, text=page) if r.url.host == "arxiv.org" else None
    ))
    store = Store(config.db_path)
    with pytest.raises(FeedError):
        fetch(D, config=config, client=client, store=store, clock=clock, sleep=Sleeps())
    assert store.candidates(D) == []
