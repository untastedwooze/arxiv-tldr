# Nightly scheduling with systemd

A systemd user timer runs `arxiv-tldr run` Sunday-Thursday at 21:30 America/New_York, after
arXiv's ~20:00 ET Announcement. `run` takes no date for the nightly schedule: it defaults to today's Announcement date
in America/New_York. `Persistent=true` means a run missed while the machine was asleep or off
happens when it comes back. The run checks that each RSS feed holds the Announcement's listing (arXiv labels it with the
next day) and, while the feed is still on the previous release, sleeps and retries (up to
the 04:00 ET cutoff), so the service may run for hours; it has no start timeout.

## Install

1. Edit `deploy/systemd/arxiv-tldr.service`: set `WorkingDirectory` and `EnvironmentFile` to
   your checkout (it holds `config.toml` and `.env`) and `ExecStart` to your `uv` path
   (`command -v uv`).
2. Install and enable:

```
mkdir -p ~/.config/systemd/user
cp deploy/systemd/arxiv-tldr.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now arxiv-tldr.timer
loginctl enable-linger "$USER"   # optional: run even when not logged in
```

## Check

```
systemctl --user list-timers arxiv-tldr.timer   # next/last trigger
systemctl --user status arxiv-tldr.service
journalctl --user -u arxiv-tldr.service -e      # logs (add -f to follow)
systemctl --user start arxiv-tldr.service       # run now, manually
```

## Validate the unit files

```
systemd-analyze verify deploy/systemd/arxiv-tldr.service deploy/systemd/arxiv-tldr.timer
systemd-analyze calendar 'Sun,Mon,Tue,Wed,Thu 21:30 America/New_York' --iterations=5
```

Note: systemd rejects the wrapping range `Sun..Thu`, so the timer spells the days out. The
`America/New_York` suffix in `OnCalendar` needs systemd 252 or newer.

## Backfill: running a missed Announcement

`arxiv-tldr run <date>` with a date earlier than the current Announcement is a backfill. (RSS
only ever holds the latest release, so it cannot supply a past one.) It sends a Late Digest
whose subject and heading read "Late Digest for <evening>".

- Within roughly the last 90 days the Candidates come from arXiv's catchup listing
  (`arxiv.org/catchup/<category>/<next day>`): exactly the new and cross-listed papers
  announced that evening. Catchup pages are fetched 15 s apart (arXiv's robots.txt
  Crawl-delay; `catchup_delay_seconds`).
- Older dates (catchup answers HTTP 400) are reconstructed from the arXiv API's submission
  dates, at least 3 s between requests (`api_delay_seconds`). The Late Digest then says the
  Candidates were inferred and papers held for moderation or cross-listed later may be
  missing (about 80% recall in a sample). Friday and Saturday evenings have no Announcement,
  and arXiv holidays are not detected.
- A backfill runs once: no retry loop, no Failure Notice. A failure (Ollama, catchup or the API
  unreachable, nothing triaged, mail rejected) prints `arxiv-tldr: <reason>` and exits
  non-zero; just rerun it. Stored Candidates, Triage results and Summaries are reused.
- Nothing blocks it: an existing Digest or Failure Notice for the date does not stop it, and
  a sent Digest is sent again.
- A future date is refused. `fetch <date>` uses the same source selection as `run`.
