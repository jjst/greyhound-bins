# greyhound-bins

Fetch your [Greyhound Recycling](https://greyhound.ie/) bin-collection schedule
and print it as a table / JSON, or generate an iCalendar (`.ics`) file to import
into Google Calendar (or any calendar app).

Greyhound's customer portal (`app.greyhound.ie`, the same backend their mobile
app wraps) embeds the full rolling-year collection calendar as JSON once you log
in. This script logs in with your account number + PIN, reads that JSON, and
renders it.

Acknowledgements: the login/parse approach is adapted from the Home Assistant
[`waste_collection_schedule`](https://github.com/mampfes/hacs_waste_collection_schedule)
project (`greyhound_ie.py` source).

## Requirements

- [`uv`](https://docs.astral.sh/uv/) (handles Python 3.10+ and the `requests`
  dependency automatically — nothing else to install)

## Credentials

Credentials are read from the environment:

- `GREYHOUND_ACCOUNT` — your account / customer number
- `GREYHOUND_PIN` — your PIN

These are the same details you use to sign into the Greyhound app.

## Usage

The script carries inline [PEP 723](https://peps.python.org/pep-0723/)
metadata, so `uv run` fetches Python and `requests` on the fly — no venv setup.
Dependencies are hash-pinned in `fetch_schedule.py.lock`, which `uv` picks up
automatically:

```sh
# Full rolling-year schedule as a table (default)
uv run fetch_schedule.py

# Just the next 4 weeks
uv run fetch_schedule.py --weeks 4

# An .ics for the next 6 weeks, written to a file
uv run fetch_schedule.py --format ics --weeks 6 --out bins.ics

# Only green-bin days, as JSON
uv run fetch_schedule.py --format json --bins green

# For extra flags and options (custom output type, reminder configuration, bin type inclusion/exclusion...
uv run fetch_schedule.py --help
```

Import the generated `.ics` via Google Calendar → **Settings → Import & export
→ Import**. Each event has a stable UID per date, so re-importing an updated
file **updates events in place rather than duplicating** them.

## Security notes

- The only network traffic is one HTTPS login + fetch against `app.greyhound.ie`,
  as the Greyhound app does. Credentials come from the environment and are never
  logged, echoed in errors, or written to disk.
- Each run is a single login attempt, so a cron job with stale credentials will
  repeatedly fail against your account. Check them before scheduling.
- To refresh pinned dependencies: `uv lock --script fetch_schedule.py --upgrade`.

## Notes

- The portal returns a ~12-month rolling window, so re-run roughly yearly to
  refresh.
- Bin types seen: `GREEN`, `BLACK`, `BROWN` (a date can have more than one).
