# Nightly scheduling with systemd

A systemd user timer runs `arxiv-tldr run` Sunday-Thursday at 21:30 America/New_York, after
arXiv's ~20:00 ET Announcement. `run` takes no date: it defaults to today's Announcement date
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
