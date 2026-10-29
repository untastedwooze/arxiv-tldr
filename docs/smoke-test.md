# Smoke test against piglet

Runs one real Announcement end to end (real arXiv, real Ollama, real httpx client) with a
recording Mailer, then reports from the Store. No email is sent unless you pass `--send`;
instead the Digest HTML is written next to the DB (`digest-<date>.html`) and its path printed.

```
uv run python scripts/smoke_piglet.py --date 2026-10-26      # or: uv run python -m arxiv_tldr.smoke
uv run python scripts/smoke_piglet.py --db smoke.db --send   # keep the DB, really email the Digest
```

Config comes from the usual `config.toml` / `.env` (Ollama URL, model, profile). The Store
defaults to a fresh temp file, so reruns start clean; the DB path is printed.

The report shows per-call and total Triage/Summary timings (`call_timings`), the Relevance
Score distribution, and Summary sources (html / pdf / abstract, plus how many were cut).

There is also a pytest live test, excluded by default (marker `live`, skipped unless set):

```
ARXIV_TLDR_LIVE=1 uv run pytest -m live
```
