"""Triage: score every untriaged Candidate against the Interest Profile."""

from datetime import date

from pydantic import BaseModel, Field

from .llm import BadLLMOutput, OllamaClient
from .store import Candidate, Store


class TriageVerdict(BaseModel):
    # Field order matters: the Rationale is generated before the score.
    rationale: str = Field(description="One sentence explaining the score.")
    score: int = Field(ge=1, le=10, description="Relevance to the Interest Profile, 1-10.")


def build_prompt(profile: str, candidate: Candidate) -> str:
    """Interest Profile first, so Ollama can reuse the cached prefix across calls."""
    categories = ", ".join([candidate.primary_category, *candidate.cross_list_categories])
    return (
        f"{profile.strip()}\n\n"
        "----\n"
        "Judge how relevant the paper below is to the reader described above. "
        "Write a one-sentence rationale first, then a relevance score from 1 (irrelevant) "
        "to 10 (must read).\n\n"
        f"Title: {candidate.title}\n"
        f"Categories: {categories}\n"
        f"Abstract: {candidate.abstract}\n"
    )


def triage(announcement: date, *, profile: str, llm: OllamaClient, store: Store) -> int:
    """Triage the Candidates with no stored result; returns how many were scored.

    A Candidate whose output stays invalid is left untriaged; an unreachable host propagates.
    """
    scored = 0
    for candidate in store.untriaged(announcement):
        try:
            verdict, seconds = llm.generate(build_prompt(profile, candidate), TriageVerdict)
        except BadLLMOutput:
            continue
        store.add_triage_result(
            announcement, candidate.arxiv_id,
            score=verdict.score, rationale=verdict.rationale, model=llm.model, seconds=seconds,
        )
        scored += 1
    return scored
