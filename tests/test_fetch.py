from datetime import date

import httpx

from arxiv_tldr.cli import main
from arxiv_tldr.config import Config, load_config
from arxiv_tldr.feed import fetch
from arxiv_tldr.store import Store

from conftest import rss_transport

FEEDS = {"q-fin": "rss_q-fin.xml", "stat.ME": "rss_stat.ME.xml"}
D = date(2026, 10, 26)


def make(tmp_path, feeds=FEEDS, categories=("q-fin", "stat.ME")):
    config = Config(watched_categories=categories, db_path=tmp_path / "t.db")
    client = httpx.Client(transport=rss_transport(feeds))
    return config, client, Store(config.db_path)


def test_fetch_records_new_and_cross_list_candidates_only(tmp_path, clock):
    config, client, store = make(tmp_path)
    fetch(D, config=config, client=client, store=store, clock=clock)

    by_id = {c.arxiv_id: c for c in store.candidates(D)}
    # replace and replace-cross are excluded; duplicate merged
    assert sorted(by_id) == ["2610.00001", "2610.00002", "2610.00004", "2610.00006"]

    c = by_id["2610.00001"]
    assert c.title == "Volatility Forecasting with Rough Paths"
    assert c.authors == ["Alice Smith", "Bob Jones", "Carol Lee", "Dan Wu"]
    assert c.abstract == "We forecast volatility using rough path signatures."
    assert c.primary_category == "q-fin.ST"
    assert c.cross_list_categories == []
    assert c.announce_type == "new"
    assert c.abs_url == "https://arxiv.org/abs/2610.00001"
    assert c.html_url == "https://arxiv.org/html/2610.00001"
    assert c.pdf_url == "https://arxiv.org/pdf/2610.00001"

    x = by_id["2610.00004"]  # primary category outside the Watched Categories
    assert x.primary_category == "math.OC"
    assert x.cross_list_categories == ["q-fin.PM"]
    assert x.announce_type == "cross"


def test_candidate_in_two_watched_categories_is_one_candidate(tmp_path, clock):
    config, client, store = make(tmp_path)
    fetch(D, config=config, client=client, store=store, clock=clock)
    dup = [c for c in store.candidates(D) if c.arxiv_id == "2610.00002"]
    assert len(dup) == 1
    assert dup[0].primary_category == "q-fin.ST"
    assert dup[0].cross_list_categories == ["stat.ME"]
    assert dup[0].abstract == "A study of tail behaviour & estimation."
    assert dup[0].announce_type == "new"


def test_refetching_same_date_does_not_duplicate(tmp_path, clock):
    config, client, store = make(tmp_path)
    fetch(D, config=config, client=client, store=store, clock=clock)
    fetch(D, config=config, client=client, store=store, clock=clock)
    assert len(store.candidates(D)) == 4


def test_same_paper_on_another_announcement_is_a_separate_candidate(tmp_path, clock):
    config, client, store = make(tmp_path)
    fetch(D, config=config, client=client, store=store, clock=clock)
    fetch(date(2026, 10, 27), config=config, client=client, store=store, clock=clock)
    assert len(store.candidates(D)) == 4
    assert len(store.candidates(date(2026, 10, 27))) == 4


def test_only_watched_categories_are_requested(tmp_path, clock):
    requests = []
    config = Config(watched_categories=("stat.ME",), db_path=tmp_path / "t.db")
    client = httpx.Client(transport=rss_transport(FEEDS, requests))
    fetch(D, config=config, client=client, store=Store(config.db_path), clock=clock)
    assert [r.url.path for r in requests] == ["/rss/stat.ME"]


def test_empty_feeds_record_nothing(tmp_path, clock):
    config, client, store = make(
        tmp_path, feeds={"q-fin": "rss_empty.xml", "stat.ME": "rss_empty.xml"}
    )
    fetch(D, config=config, client=client, store=store, clock=clock)
    assert store.candidates(D) == []


def test_cli_fetch_subcommand(tmp_path, clock, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.toml").write_text(
        'watched_categories = ["q-fin", "stat.ME"]\ndb_path = "cli.db"\n'
    )
    client = httpx.Client(transport=rss_transport(FEEDS))
    code = main(["fetch", "2026-10-26"], client=client, clock=clock)
    assert code == 0
    assert len(Store(tmp_path / "cli.db").candidates(D)) == 4


def test_default_watched_categories_match_spec():
    assert Config().watched_categories == (
        "q-fin", "stat.ME", "econ.EM",
    )


def test_config_reads_env_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("ARXIV_TLDR_DB_PATH=from_env.db\n")
    monkeypatch.delenv("ARXIV_TLDR_DB_PATH", raising=False)
    assert load_config().db_path.name == "from_env.db"
