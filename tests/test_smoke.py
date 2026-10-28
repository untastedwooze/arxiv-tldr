import os
from datetime import date

import pytest

from arxiv_tldr.smoke import format_report, smoke_report
from arxiv_tldr.store import Candidate, Store

D = date(2026, 10, 26)


def cand(i: str) -> Candidate:
    return Candidate(
        arxiv_id=i, title=f"Paper {i}", authors=["A"], abstract="abs", primary_category="q-fin.ST",
        cross_list_categories=[], announce_type="new", abs_url="u", html_url="u", pdf_url="u",
    )


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "s.db")
    s.add_candidates(D, [cand(i) for i in ("1", "2", "3", "4")])
    for i, score, secs in (("1", 9, 1.0), ("2", 9, 3.0), ("3", 4, 2.0), ("4", 7, 2.0)):
        s.add_triage_result(D, i, score=score, rationale="r", model="m", seconds=secs)
    for i, source, cut, secs in (("1", "html", False, 10.0), ("2", "pdf", True, 30.0)):
        s.add_summary(D, i, fields={"tldr": "t"}, source=source, cut=cut, model="m", seconds=secs)
    return s


def test_report_timings_scores_and_sources(store):
    r = smoke_report(store, D)

    assert r.triage.count == 4
    assert r.triage.total_seconds == 8.0
    assert r.triage.mean_seconds == 2.0
    assert r.triage.max_seconds == 3.0
    assert r.summary.count == 2
    assert r.summary.total_seconds == 40.0
    assert r.score_distribution == {4: 1, 7: 1, 9: 2}
    assert r.source_breakdown == {"html": 1, "pdf": 1, "abstract": 0, "cut": 1}


def test_format_report_lists_per_call_timings(store):
    text = format_report(smoke_report(store, D), store.call_timings(D))

    assert "summary  2" in text and "30.0s" in text
    assert "score  9: 2" in text
    assert "cut: 1" in text


def test_empty_store_reports_zeroes(tmp_path):
    r = smoke_report(Store(tmp_path / "e.db"), D)
    assert r.triage.count == 0 and r.triage.mean_seconds == 0.0
    assert r.score_distribution == {}


@pytest.mark.live
@pytest.mark.skipif(
    not os.environ.get("ARXIV_TLDR_LIVE"), reason="set ARXIV_TLDR_LIVE=1 to hit real Ollama"
)
def test_live_smoke(tmp_path):
    from arxiv_tldr.smoke import main

    assert main(["--db", str(tmp_path / "live.db"), "--date", date.today().isoformat()]) == 0
