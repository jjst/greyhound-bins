# greyhound-bins

Fetch your [Greyhound Recycling](https://greyhound.ie/) bin-collection schedule
and print it as a table / JSON, or generate an iCalendar (`.ics`) file to import
into Google Calendar (or any calendar app).

Greyhound's customer portal (`app.greyhound.ie`, the same backend their mobile
app wraps) embeds the full rolling-year collection calendar as JSON once you log
in. This script logs in with your account number + PIN, reads that JSON, and
renders it. No PDF parsing, no scraping of coordinates.

The login/parse approach is adapted from the Home Assistant
[`waste_collection_schedule`](https://github.com/mampfes/hacs_waste_collection_schedule)
project (`greyhound_ie.py` source).

## Requirements

- [`uv`](https://docs.astral.sh/uv/) (handles Python 3.10+ and the `requests`
  dependency automatically — nothing else to install)

## Credentials

Credentials are read from the environment — never hard-coded:

- `GREYHOUND_ACCOUNT` — your account / customer number
- `GREYHOUND_PIN` — your PIN

These are the same details you use to sign into the Greyhound app.

If you keep them in [`pass`](https://www.passwordstore.org/):

```sh
export GREYHOUND_ACCOUNT=1234567
export GREYHOUND_PIN="$(pass greyhound.ie/1234567 | head -n1)"
```

## Usage

The script carries inline [PEP 723](https://peps.python.org/pep-0723/)
metadata, so `uv run` fetches Python and `requests` on the fly — no venv setup:

```sh
# Full rolling-year schedule as a table (default)
uv run fetch_schedule.py

# Just the next 4 weeks
uv run fetch_schedule.py --weeks 4

# An .ics for the next 6 weeks, written to a file
uv run fetch_schedule.py --format ics --weeks 6 --out bins.ics

# Only green-bin days, as JSON
uv run fetch_schedule.py --format json --bins green
```

Or install it as a command in the project environment:

```sh
uv run greyhound-bins --weeks 4
```

Import the generated `.ics` via Google Calendar → **Settings → Import & export
→ Import**. Each event has a stable UID per date, so re-importing an updated
file **updates events in place rather than duplicating** them.

## Options

| Flag | Description |
|------|-------------|
| `--format {table,json,ics}` | Output format (default: `table`) |
| `--out FILE` | Write to a file instead of stdout |
| `--from YYYY-MM-DD` | Only collections on/after this date |
| `--to YYYY-MM-DD` | Only collections on/before this date |
| `--weeks N` | Only the next N weeks (from `--from`, or today) |
| `--bins LIST` | Comma-separated types to include, e.g. `green,brown` |
| `--no-reminder` | Omit the reminder/alarm from `.ics` events |
| `--reminder-time HH:MM` | Reminder clock time (default: `18:00`) |
| `--reminder-days-before N` | Days before collection to remind (default: `1`) |
| `--reminder-method {popup,email}` | Reminder delivery (default: `popup`) |
| `--no-emoji` | Plain-text titles without bin-colour emoji |
| `--calendar-name NAME` | `.ics` calendar name (default: `Bin Collection`) |
| `--uid-prefix PREFIX` | Prefix for event UIDs (default: `greyhound`) |

## Notes

- The portal returns a ~12-month rolling window, so re-run roughly yearly to
  refresh.
- Bin types seen: `GREEN`, `BLACK`, `BROWN` (a date can have more than one).
- Generated `.ics` files are git-ignored — they contain your personal schedule.
