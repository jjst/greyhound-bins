#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["requests>=2.31"]
#
# [[tool.uv.index]]
# url = "https://pypi.org/simple"
# default = true
# ///
"""Fetch the Greyhound Recycling bin-collection schedule for an account.

Logs into the Greyhound customer portal (the same backend the mobile app wraps),
reads the embedded collection-calendar JSON, and prints the full schedule.

Credentials come from the environment, never from code:
    GREYHOUND_ACCOUNT   customer / account number
    GREYHOUND_PIN       PIN

Output:
    --format table   human-readable table + next collection (default)
    --format json    {"YYYY-MM-DD": ["GREEN", ...], ...}

Approach adapted from the Home Assistant waste_collection_schedule source
(mampfes/hacs_waste_collection_schedule, greyhound_ie.py).
"""

import argparse
import html
import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone

import requests

LOGIN_URL = "https://app.greyhound.ie/"
COLLECTION_URL = "https://app.greyhound.ie/collection/collection_calendar"

BIN_LABEL = {"GREEN": "🟢 Green", "BLACK": "⚫ Black", "BROWN": "🟤 Brown"}
BIN_WORD = {"GREEN": "Green", "BLACK": "Black", "BROWN": "Brown"}
BIN_EMOJI = {"GREEN": "🟢", "BLACK": "⚫", "BROWN": "🟤"}
BIN_PURPOSE = {
    "GREEN": "mixed dry recycling",
    "BLACK": "general / residual waste",
    "BROWN": "organic (food & garden) waste",
}
BIN_MARKER = "🗑️"  # constant lead glyph so bin events read as a series


class GreyhoundError(Exception):
    pass


def fetch_collection_days(account: str, pin: str) -> dict[str, list[str]]:
    """Return {date_str: [BIN_TYPE, ...]} for the full published calendar."""
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})

    # 1. Load the login page and scrape the CSRF token.
    resp = session.get(LOGIN_URL, timeout=30)
    resp.raise_for_status()
    m = re.search(
        r'name=["\']csrfmiddlewaretoken["\']\s+value=["\']([^"\']+)["\']', resp.text
    )
    if not m:
        raise GreyhoundError("CSRF token not found — portal layout may have changed.")
    csrf = m.group(1)

    # 2. Log in (form POST carrying the token + credentials).
    login = session.post(
        LOGIN_URL,
        data={
            "csrfmiddlewaretoken": csrf,
            "customerNo": account,
            "pinCode": pin,
        },
        headers={"Referer": LOGIN_URL},
        timeout=30,
    )
    login.raise_for_status()

    # 3. Fetch the collection calendar page.
    cal = session.get(COLLECTION_URL, timeout=30)
    cal.raise_for_status()

    # 4. The calendar data is embedded in a `var data = "...";` string whose
    #    (HTML-escaped) content holds a JSON blob, ending before getJSONData.
    m = re.search(r'var data = "(.*?)getJSONData', cal.text, re.DOTALL)
    if not m:
        if "customerNo" in cal.text or "pinCode" in cal.text:
            raise GreyhoundError(
                "Login appears to have failed (got the sign-in page back). "
                "Check GREYHOUND_ACCOUNT / GREYHOUND_PIN."
            )
        raise GreyhoundError("Could not find embedded calendar data.")

    unescaped = html.unescape(m.group(1))
    json_match = re.search(r"({.*?})\"", unescaped, re.DOTALL)
    if not json_match:
        raise GreyhoundError("Failed to extract JSON payload from calendar page.")

    try:
        raw = json.loads(json_match.group(1))
        collection_days = raw["data"]["collection_days"]
    except (json.JSONDecodeError, KeyError) as err:
        raise GreyhoundError(f"Invalid calendar data format: {err}") from err

    # Normalise to {date_str: sorted unique bin types}.
    out: dict[str, list[str]] = {}
    for date_str, entries in collection_days.items():
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            continue
        types: set[str] = set()
        for entry in entries:
            for wt in entry.get("waste_types", []):
                types.add(wt.strip().upper())
        if types:
            out[date_str] = sorted(types)
    return dict(sorted(out.items()))


def event_title(types: list[str], emoji: bool, style: str = "collection") -> str:
    """Build the event summary.

    style="collection" (default): time-neutral fact, e.g.
        "🗑️🟢 Green bin collection" / "🗑️⚫🟤 Black + Brown bin collection"
        / "🗑️⚫🟤🟢 All bins collection".
    style="action": the older imperative, e.g. "🟢 Green bin out".
    With emoji, the title always leads with 🗑️ (collection style) so bin
    events read as a recognizable series.
    """
    words = [BIN_WORD.get(t, t.title()) for t in types]
    if style == "action":
        summary = " + ".join(words) + (" bins" if len(types) > 1 else " bin") + " out"
        if emoji:
            return f"{''.join(BIN_EMOJI.get(t, '') for t in types)} {summary}"
        return summary

    # collection style
    if len(types) >= 3:
        summary = "All bins collection"
    else:
        summary = " + ".join(words) + " bin collection"
    if emoji:
        glyphs = BIN_MARKER + "".join(BIN_EMOJI.get(t, "") for t in types)
        return f"{glyphs} {summary}"
    return summary


def build_description(date_str: str, types: list[str]) -> str:
    """Plain multi-line event description: collection date, the action with
    its real timing, and what each bin is for."""
    dt = datetime.strptime(date_str, "%Y-%m-%d").date()
    when = f"{dt:%a %d %b %Y}"
    lines = [f"Collection: {when}."]
    if len(types) == 1:
        lines.append(
            f"Put the {BIN_WORD.get(types[0], types[0].title()).upper()} bin out "
            f"before 6am (the evening before is fine)."
        )
    else:
        lines.append("Put these bins out before 6am (the evening before is fine):")
    lines.append("")
    lines.append("What goes in:")
    for t in types:
        lines.append(
            f"  {BIN_EMOJI.get(t, '')} {BIN_WORD.get(t, t.title())} "
            f"· {BIN_PURPOSE.get(t, 'waste')}"
        )
    lines.append("")
    lines.append(
        "Auto-generated from Greyhound (greyhound.ie). Re-importing the bins "
        "calendar updates this event in place, so avoid editing by hand."
    )
    return "\n".join(lines)


def ics_escape(text: str) -> str:
    """Escape a text value per RFC 5545 (backslash, comma, semicolon, newline)."""
    return (
        text.replace("\\", "\\\\")
        .replace(",", "\\,")
        .replace(";", "\\;")
        .replace("\n", "\\n")
    )


def ics_fold(line: str) -> str:
    """Fold a content line to <=75 octets, continuing with CRLF + space.

    Folding is done on UTF-8 byte boundaries so multi-byte chars stay intact.
    """
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    chunks = []
    start = 0
    limit = 75
    while start < len(raw):
        end = min(start + limit, len(raw))
        # don't split a multi-byte UTF-8 sequence: back off to a boundary
        while end < len(raw) and (raw[end] & 0xC0) == 0x80:
            end -= 1
        chunks.append(raw[start:end])
        start = end
        limit = 74  # continuation lines carry a leading space
    return "\r\n ".join(c.decode("utf-8") for c in chunks)


def build_ics(
    days: dict[str, list[str]],
    *,
    reminder: bool = True,
    reminder_offset_min: int = 360,
    reminder_method: str = "popup",
    cal_name: str = "Bin Collection",
    uid_prefix: str = "greyhound",
    emoji: bool = True,
    title_style: str = "collection",
) -> str:
    """Build an iCalendar feed: one all-day event per collection day.

    Each event gets a stable UID (``<uid_prefix>-YYYYMMDD``) so re-importing
    updates in place rather than duplicating. A reminder (VALARM) is added
    unless disabled; ``reminder_offset_min`` is minutes before the event's
    midnight start (e.g. 360 = 18:00 the evening before).
    """
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    action = "EMAIL" if reminder_method == "email" else "DISPLAY"
    if reminder_offset_min >= 0:
        trigger = f"-PT{reminder_offset_min}M"
    else:
        trigger = f"PT{-reminder_offset_min}M"

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//greyhound-bins//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{ics_escape(cal_name)}",
    ]
    for d, types in days.items():
        dt = datetime.strptime(d, "%Y-%m-%d").date()
        compact = dt.strftime("%Y%m%d")
        end = (dt + timedelta(days=1)).strftime("%Y%m%d")
        title = event_title(types, emoji, title_style)
        plain = event_title(types, emoji=False, style=title_style)
        description = build_description(d, types)
        lines += [
            "BEGIN:VEVENT",
            f"UID:{uid_prefix}-{compact}@greyhound-bins",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{compact}",
            f"DTEND;VALUE=DATE:{end}",
            f"SUMMARY:{ics_escape(title)}",
            f"DESCRIPTION:{ics_escape(description)}",
            "TRANSP:TRANSPARENT",
        ]
        if reminder:
            lines += [
                "BEGIN:VALARM",
                f"ACTION:{action}",
                f"SUMMARY:{ics_escape(plain)}",
                f"DESCRIPTION:{ics_escape(plain)}",
                f"TRIGGER:{trigger}",
                "END:VALARM",
            ]
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(ics_fold(ln) for ln in lines) + "\r\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch Greyhound bin schedule.")
    ap.add_argument("--format", choices=["table", "json", "ics"], default="table")
    ap.add_argument("--out", help="write output to this file instead of stdout")
    ap.add_argument("--from", dest="start", metavar="YYYY-MM-DD",
                    help="only include collections on/after this date (default: today if --weeks is set, else no lower bound)")
    ap.add_argument("--to", dest="end", metavar="YYYY-MM-DD",
                    help="only include collections on/before this date")
    ap.add_argument("--weeks", type=int, metavar="N",
                    help="only include the next N weeks (from --from, or today)")
    ap.add_argument("--bins", metavar="LIST",
                    help="comma-separated bin types to include, e.g. green,brown "
                         "(default: all)")

    rem = ap.add_argument_group("reminder options (ics)")
    rem.add_argument("--no-reminder", action="store_true",
                     help="omit the reminder/alarm from events")
    rem.add_argument("--reminder-time", metavar="HH:MM", default="18:00",
                     help="clock time of the reminder (default: 18:00)")
    rem.add_argument("--reminder-days-before", type=int, default=1, metavar="N",
                     help="how many days before collection to remind (default: 1; 0 = same day)")
    rem.add_argument("--reminder-method", choices=["popup", "email"], default="popup",
                     help="reminder delivery method (default: popup)")

    pres = ap.add_argument_group("presentation options")
    pres.add_argument("--title-style", choices=["collection", "action"],
                      default="collection",
                      help="event title wording: 'collection' (default, e.g. "
                           "'Green bin collection') or 'action' ('Green bin out')")
    pres.add_argument("--no-emoji", action="store_true",
                      help="plain-text titles without bin emoji")
    pres.add_argument("--calendar-name", default="Bin Collection", metavar="NAME",
                      help="ics calendar name (X-WR-CALNAME; default: 'Bin Collection')")
    pres.add_argument("--uid-prefix", default="greyhound", metavar="PREFIX",
                      help="prefix for event UIDs (default: greyhound)")
    args = ap.parse_args()

    # reminder offset: minutes before the event's midnight start
    try:
        rh, rm = (int(x) for x in args.reminder_time.split(":"))
        if not (0 <= rh < 24 and 0 <= rm < 60):
            raise ValueError
    except ValueError:
        print(f"error: --reminder-time must be HH:MM (got {args.reminder_time!r})",
              file=sys.stderr)
        return 2
    reminder_offset_min = args.reminder_days_before * 1440 - (rh * 60 + rm)

    bin_filter = None
    if args.bins:
        bin_filter = {b.strip().upper() for b in args.bins.split(",") if b.strip()}
        unknown = bin_filter - set(BIN_WORD)
        if unknown:
            print(f"error: unknown bin type(s): {', '.join(sorted(unknown))}. "
                  f"Valid: {', '.join(w.lower() for w in BIN_WORD)}", file=sys.stderr)
            return 2

    def parse_date(val, flag):
        try:
            return datetime.strptime(val, "%Y-%m-%d").date()
        except ValueError:
            print(f"error: {flag} must be YYYY-MM-DD (got {val!r})", file=sys.stderr)
            raise SystemExit(2)

    lo = parse_date(args.start, "--from") if args.start else None
    hi = parse_date(args.end, "--to") if args.end else None
    if args.weeks is not None:
        base = lo or date.today()
        window_end = base + timedelta(weeks=args.weeks)
        hi = min(hi, window_end) if hi else window_end
        lo = base

    account = os.environ.get("GREYHOUND_ACCOUNT")
    pin = os.environ.get("GREYHOUND_PIN")
    if not account or not pin:
        print(
            "error: set GREYHOUND_ACCOUNT and GREYHOUND_PIN in the environment.",
            file=sys.stderr,
        )
        return 2

    try:
        days = fetch_collection_days(account, pin)
    except (requests.RequestException, GreyhoundError) as err:
        print(f"error: {err}", file=sys.stderr)
        return 1

    if not days:
        print("No collection days found for this account.", file=sys.stderr)
        return 1

    if lo or hi:
        days = {
            d: t for d, t in days.items()
            if (lo is None or datetime.strptime(d, "%Y-%m-%d").date() >= lo)
            and (hi is None or datetime.strptime(d, "%Y-%m-%d").date() <= hi)
        }
        if not days:
            print("No collection days in the requested range.", file=sys.stderr)
            return 1

    if bin_filter is not None:
        days = {
            d: [t for t in types if t in bin_filter]
            for d, types in days.items()
        }
        days = {d: t for d, t in days.items() if t}
        if not days:
            print("No collection days match the requested bin type(s).", file=sys.stderr)
            return 1

    if args.format in ("json", "ics"):
        if args.format == "json":
            out = json.dumps(days, indent=2)
        else:
            out = build_ics(
                days,
                reminder=not args.no_reminder,
                reminder_offset_min=reminder_offset_min,
                reminder_method=args.reminder_method,
                cal_name=args.calendar_name,
                uid_prefix=args.uid_prefix,
                emoji=not args.no_emoji,
                title_style=args.title_style,
            )
        if args.out:
            with open(args.out, "w", encoding="utf-8") as fh:
                fh.write(out)
            print(f"Wrote {len(days)} collection days to {args.out}", file=sys.stderr)
        else:
            print(out)
        return 0

    # table
    today = date.today()
    next_date = next((d for d in days if datetime.strptime(d, "%Y-%m-%d").date() >= today), None)
    print(f"Greyhound bin collection — {len(days)} dates "
          f"({min(days)} to {max(days)})\n")
    label_map = BIN_WORD if args.no_emoji else BIN_LABEL
    for d, types in days.items():
        dt = datetime.strptime(d, "%Y-%m-%d").date()
        marker = "→" if d == next_date else " "
        labels = "  ".join(label_map.get(t, t) for t in types)
        print(f" {marker} {dt:%a %d %b %Y}   {labels}")
    if next_date:
        nd = datetime.strptime(next_date, "%Y-%m-%d").date()
        days_away = (nd - today).days
        when = "today" if days_away == 0 else ("tomorrow" if days_away == 1 else f"in {days_away} days")
        labels = "  ".join(label_map.get(t, t) for t in days[next_date])
        print(f"\nNext collection: {nd:%a %d %b %Y} ({when}) — {labels}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
