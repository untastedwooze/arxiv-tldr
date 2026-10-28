from arxiv_tldr.selection import select
from arxiv_tldr.store import Candidate, TriagedCandidate


def tc(arxiv_id, score):
    return TriagedCandidate(
        candidate=Candidate(
            arxiv_id=arxiv_id, title=f"T{arxiv_id}", authors=[], abstract="",
            primary_category="q-fin.ST", cross_list_categories=[], announce_type="new",
            abs_url="", html_url="", pdf_url="",
        ),
        score=score, rationale="r", model="m",
    )


def ids(items):
    return [t.candidate.arxiv_id for t in items]


def test_below_threshold_is_never_featured():
    result = select([tc("a", 6), tc("b", 7), tc("c", 10)], threshold=7, cap=15)
    assert ids(result.featured) == ["c", "b"]
    assert result.overflow == []


def test_cap_limits_featured_and_rest_overflow():
    papers = [tc("a", 8), tc("b", 9), tc("c", 7), tc("d", 10)]
    result = select(papers, threshold=7, cap=2)
    assert ids(result.featured) == ["d", "b"]
    assert ids(result.overflow) == ["a", "c"]


def test_ties_break_by_arxiv_id():
    papers = [tc("2610.00003", 8), tc("2610.00001", 8), tc("2610.00002", 8)]
    result = select(papers, threshold=7, cap=2)
    assert ids(result.featured) == ["2610.00001", "2610.00002"]
    assert ids(result.overflow) == ["2610.00003"]
