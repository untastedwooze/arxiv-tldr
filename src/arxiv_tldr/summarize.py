"""Summarize: write a structured Summary for each Featured Paper that has none yet."""

import logging
from datetime import date

import httpx
from pydantic import BaseModel, Field

from .fulltext import FullText, obtain
from .llm import BadLLMOutput, OllamaClient
from .store import Candidate, Store, TriagedCandidate

log = logging.getLogger(__name__)


class Summary(BaseModel):
    """The Summary shape: the JSON schema sent to Ollama and the validator of its answer."""

    # Per-field word limits: the model ignores a total budget but follows these.
    tldr: str = Field(description="One sentence, at most 30 words: the paper in a nutshell.")
    problem: str = Field(description="The problem addressed, at most 2 sentences / 40 words.")
    method: str = Field(description="The approach taken, at most 2 sentences / 40 words.")
    data: str = Field(
        description="The data used, at most 1 sentence / 25 words, or 'None' for purely "
        "theoretical work."
    )
    key_results: str = Field(
        description="At most 3 main findings, numbered, with numbers where given; "
        "at most 60 words in total."
    )
    limitations: str = Field(
        description="Limitations and caveats, at most 2 sentences / 40 words."
    )


# Digest labels, in display order.
SUMMARY_LABELS = {
    "tldr": "TL;DR",
    "problem": "Problem",
    "method": "Method",
    "data": "Data",
    "key_results": "Key results",
    "limitations": "Limitations / caveats",
}


def build_prompt(profile: str, candidate: Candidate, full_text: FullText) -> str:
    """Interest Profile first, so Ollama can reuse the cached prefix across calls."""
    kind = "abstract" if full_text.source == "abstract" else "full text"
    return (
        f"{profile.strip()}\n\n"
        "----\n"
        f"Summarize the paper below for the reader described above, from its {kind}. "
        "Fill every field tersely and keep within each field's word limit; the whole "
        "summary must be under 200 words. Do not restate the reader's interests.\n\n"
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
        log.info("summarizing %s from %s%s", candidate.arxiv_id, full_text.source,
                 " (cut)" if full_text.cut else "")
        try:
            summary, seconds = llm.generate(
                build_prompt(profile, candidate, full_text), Summary, num_ctx=num_ctx
            )
        except BadLLMOutput as exc:
            log.warning("summary %s: invalid model output: %s", candidate.arxiv_id, exc)
            continue
        log.info("summarized %s (%.1fs)", candidate.arxiv_id, seconds)
        store.add_summary(
            announcement, candidate.arxiv_id, fields=summary.model_dump(),
            source=full_text.source, cut=full_text.cut, model=llm.model, seconds=seconds,
        )
        written += 1
    return written
