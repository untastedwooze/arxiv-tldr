"""Selection: pure split of triaged Candidates into Featured and Overflow Papers."""

from dataclasses import dataclass

from .store import TriagedCandidate


@dataclass(frozen=True)
class Selection:
    featured: list[TriagedCandidate]
    overflow: list[TriagedCandidate]


def select(triaged: list[TriagedCandidate], *, threshold: int, cap: int) -> Selection:
    """Papers scoring >= threshold, best first (ties by arXiv ID); the top ``cap`` are featured."""
    eligible = sorted(
        (t for t in triaged if t.score >= threshold),
        key=lambda t: (-t.score, t.candidate.arxiv_id),
    )
    return Selection(featured=eligible[:cap], overflow=eligible[cap:])
