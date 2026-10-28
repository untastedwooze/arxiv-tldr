"""Summarize: write a structured Summary for each Featured Paper that has none yet."""

from datetime import date

import httpx
from pydantic import BaseModel, Field

from .fulltext import FullText, obtain
from .llm import BadLLMOutput, OllamaClient
from .store import Candidate, Store, TriagedCandidate


class Summary(BaseModel):
    """The Summary shape: the JSON schema sent to Ollama and the validator of its answer."""

    tldr: str = Field(description="One or two sentences: the paper in a nutshell.")
    problem: str = Field(description="The problem addressed, briefly.")
    method: str = Field(description="The approach taken, briefly.")
    data: str = Field(description="The data used, or 'None' for purely theoretical work.")
    key_results: str = Field(description="The main findings, with numbers where given.")
    limitations: str = Field(description="Limitations and caveats, briefly.")
    why_it_matters: str = Field(
        description="Why this matters to the reader, judged against their interests."
    )


# Digest labels, in display order.
SUMMARY_LABELS = {
    "tldr": "TL;DR",
    "problem": "Problem",
    "method": "Method",
    "data": "Data",
    "key_results": "Key results",
    "limitations": "Limitations / caveats",
    "why_it_matters": "Why it matters to you",
}


def build_prompt(profile: str, candidate: Candidate, full_text: FullText) -> str:
    """Interest Profile first, so Ollama can reuse the cached prefix across calls."""
    kind = "abstract" if full_text.source == "abstract" else "full text"
    return (
        f"{profile.strip()}\n\n"
        "----\n"
        f"Summarize the paper below for the reader described above, from its {kind}. "
        "Fill every field concisely; the whole summary should be roughly 150-250 words. "
        "In why_it_matters, relate the paper to the reader's interests.\n\n"
        f"Title: {candidate.title}\n\n"
        f"{kind.capitalize()}:\n{full_text.text}\n"
    )


def summarize(
    announcement: date, featured: list[TriagedCandidate], *, profile: str, llm: OllamaClient,
    store: Store, client: httpx.Client, num_ctx: int,
    text_budget: int | None = None,
) -> int:
    """Summarize the Featured Papers with no stored Summary; returns how many were written.

    A paper whose output stays invalid is left without a Summary; an unreachable host propagates.
    """
    done = store.summaries(announcement)
    written = 0
    for triaged in featured:
        candidate = triaged.candidate
        if candidate.arxiv_id in done:
            continue
        full_text = obtain(candidate, client, budget=text_budget)
        try:
            summary, seconds = llm.generate(
                build_prompt(profile, candidate, full_text), Summary, num_ctx=num_ctx
            )
        except BadLLMOutput:
            continue
        store.add_summary(
            announcement, candidate.arxiv_id, fields=summary.model_dump(),
            source=full_text.source, cut=full_text.cut, model=llm.model, seconds=seconds,
        )
        written += 1
    return written
