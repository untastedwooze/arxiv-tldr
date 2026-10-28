from datetime import date

import httpx
from arxiv_tldr.cli import main
from arxiv_tldr.pipeline import run

from conftest import combined_transport, ollama_handler, rss_handler
from test_run import FEEDS, OLLAMA_URL, SCORES, setup

D = date(2026, 10, 26)
D_ARG = "2026-10-26"


class RejectingMailer:
    def send(self, message):
        raise RuntimeError("Gmail rejected the message")


def write_config(tmp_path):
    (tmp_path / "config.toml").write_text(
        'watched_categories = ["q-fin", "stat.ME"]\ndb_path = "t.db"\n'
        f'interest_profile_path = "profile.md"\nollama_base_url = "{OLLAMA_URL}"\n'
        'recipients = ["reader@example.com"]\n'
    )


def test_subcommands_run_step_by_step(tmp_path, clock, monkeypatch):
    config, client, mailer, requests = setup(tmp_path)
    monkeypatch.chdir(tmp_path)
    write_config(tmp_path)

    def cli(*a):
        return main(list(a), client=client, clock=clock, mailer=mailer)

    assert cli("fetch", D_ARG) == 0
    assert cli("triage", D_ARG) == 0
    assert len(requests) == 4 and mailer.sent == []
    assert cli("summarize", D_ARG) == 0
    assert mailer.sent == []
    assert cli("send", D_ARG) == 0
    assert len(mailer.sent) == 1
    assert len(requests) == 4


def test_crash_partway_through_triage_resumes_without_redoing_work(tmp_path, clock):
    config, _, mailer, _ = setup(tmp_path)
    calls = []
    inner = ollama_handler(SCORES, calls)
    state = {"crash": True}

    def flaky(request):
        response = inner(request)
        if response is not None and len(calls) == 3 and state["crash"]:
            raise httpx.ConnectError("ollama went away")
        return response

    client = httpx.Client(transport=combined_transport(rss_handler(FEEDS), flaky))
    sleeps = []

    def sleep(seconds):  # piglet comes back while the run waits to retry
        sleeps.append(seconds)
        state["crash"] = False

    run(D, config=config, client=client, mailer=mailer, clock=clock, sleep=sleep)
    assert sleeps == [1200]
    assert len(calls) == 3 + 2  # the crashed one and the remaining one only
    assert len(mailer.sent) == 1
    run(D, config=config, client=client, mailer=mailer, clock=clock)
    assert len(mailer.sent) == 1


def test_run_after_successful_send_sends_nothing(tmp_path, clock):
    config, client, mailer, requests = setup(tmp_path)
    run(D, config=config, client=client, mailer=mailer, clock=clock)
    n = len(requests)
    run(D, config=config, client=client, mailer=mailer, clock=clock)
    assert len(mailer.sent) == 1 and len(requests) == n


def test_send_after_run_sends_nothing_more(tmp_path, clock, monkeypatch):
    config, client, mailer, _ = setup(tmp_path)
    monkeypatch.chdir(tmp_path)
    write_config(tmp_path)
    main(["run", D_ARG], client=client, clock=clock, mailer=mailer)
    main(["send", D_ARG], client=client, clock=clock, mailer=mailer)
    assert len(mailer.sent) == 1


def test_rejected_send_leaves_digest_unsent_and_later_send_delivers(tmp_path, clock, monkeypatch):
    config, client, mailer, requests = setup(tmp_path)
    monkeypatch.chdir(tmp_path)
    write_config(tmp_path)
    main(["run", D_ARG], client=client, clock=clock, mailer=RejectingMailer())
    n = len(requests)
    assert main(["send", D_ARG], client=client, clock=clock, mailer=mailer) == 0
    assert len(mailer.sent) == 1
    assert len(requests) == n  # nothing re-triaged
