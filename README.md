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

This is a single-file script with inline [PEP 723](https://peps.python.org/pep-0723/)
metadata: `uv run` fetches Python and `requests` on the fly, so there is nothing
to install and no virtualenv to manage. Dependencies are hash-pinned in
`fetch_schedule.py.lock`, which `uv` picks up automatically whenever it sits
next to the script, so every run installs exactly the audited versions:

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

You don't need a clone. Download `fetch_schedule.py` and `fetch_schedule.py.lock`
into any directory and run it from there, or run it straight from GitHub for a
one-off (note this path resolves `requests` fresh and does not use the lockfile):

```sh
uv run https://raw.githubusercontent.com/jjst/greyhound-bins/main/fetch_schedule.py --weeks 4
```

If you run it regularly, a shell alias is all the "install" it needs:

```sh
alias greyhound-bins='uv run --locked /path/to/greyhound-bins/fetch_schedule.py'
```

`--locked` makes `uv` fail fast instead of re-resolving if the lockfile and the
script's metadata ever disagree (needs a recent `uv`; older releases accept the
flag for scripts but do not enforce it).

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

## Security notes

- **What leaves your machine:** a single HTTPS session to `app.greyhound.ie`
  carrying your account number + PIN in the login form, exactly as the Greyhound
  app does. Nothing is sent anywhere else, and no session cookie or credential
  is written to disk.
- **Credentials** are only ever read from `GREYHOUND_ACCOUNT` / `GREYHOUND_PIN`.
  They are never logged or included in error messages. Prefer a secret manager
  (e.g. `pass`, as above) over typing the PIN into a shell line that ends up in
  your history.
- **Generated `.ics` files** contain your personal schedule and are git-ignored.
  Treat them as private.
- **Dependencies** are hash-pinned in `fetch_schedule.py.lock`. To pick up
  newer releases (e.g. after a `requests`/`urllib3` advisory), run
  `uv lock --script fetch_schedule.py --upgrade` and commit the result.
- Each run performs **one** login attempt. If you schedule it (cron etc.), make
  sure the credentials are correct first to avoid repeated failed logins against
  your account.

## Notes

- The portal returns a ~12-month rolling window, so re-run roughly yearly to
  refresh.
- Bin types seen: `GREEN`, `BLACK`, `BROWN` (a date can have more than one).
- Generated `.ics` files are git-ignored — they contain your personal schedule.
