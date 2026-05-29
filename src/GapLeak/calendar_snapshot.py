from __future__ import annotations

import json
import os
from datetime import date, datetime, time, timedelta, timezone
from html import escape
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from .data import ATTENDEE_NAMES_BY_EMAIL, SAMPLE_EVENTS

CALENDAR_SNAPSHOT_ROOT = Path(
    os.environ.get("GAPLEAK_CALENDAR_SNAPSHOT_ROOT", "outputs/manual/scene1/calendar_snapshots")
)
RAW_ICS_PATH = CALENDAR_SNAPSHOT_ROOT / "outlook_published.ics"
SNAPSHOT_JSON_PATH = CALENDAR_SNAPSHOT_ROOT / "outlook_next10days.json"
SNAPSHOT_HTML_PATH = CALENDAR_SNAPSHOT_ROOT / "outlook_next10days.html"
SYNTHETIC_CALENDAR_OWNER_NAME = os.environ.get("GAPLEAK_CALENDAR_OWNER_NAME", "Maya Chen")
SYNTHETIC_CALENDAR_OWNER_EMAIL = os.environ.get("GAPLEAK_CALENDAR_OWNER_EMAIL", "")


def ensure_calendar_snapshot_dirs() -> Path:
    CALENDAR_SNAPSHOT_ROOT.mkdir(parents=True, exist_ok=True)
    return CALENDAR_SNAPSHOT_ROOT


def calendar_snapshot_exists() -> bool:
    return SNAPSHOT_HTML_PATH.exists() and SNAPSHOT_JSON_PATH.exists()


def load_calendar_snapshot() -> dict | None:
    if not SNAPSHOT_JSON_PATH.exists():
        return None
    return json.loads(SNAPSHOT_JSON_PATH.read_text(encoding="utf-8"))


def load_calendar_snapshot_html() -> str | None:
    if not SNAPSHOT_HTML_PATH.exists():
        return None
    return SNAPSHOT_HTML_PATH.read_text(encoding="utf-8")


def load_calendar_snapshot_html_bytes() -> bytes | None:
    if not SNAPSHOT_HTML_PATH.exists():
        return None
    return SNAPSHOT_HTML_PATH.read_bytes()


def fetch_published_calendar_ics(ics_url: str, *, timeout_seconds: float = 20.0) -> str:
    request = Request(
        ics_url,
        headers={
            "User-Agent": "gapleak-calendar-snapshot/1.0",
            "Accept": "text/calendar, text/plain;q=0.9, */*;q=0.8",
        },
    )
    with urlopen(request, timeout=timeout_seconds) as response:
        return response.read().decode("utf-8-sig")


def _us_dst_bounds(year: int) -> tuple[date, date]:
    march_1 = date(year, 3, 1)
    first_sunday_offset = (6 - march_1.weekday()) % 7
    second_sunday_in_march = march_1 + timedelta(days=first_sunday_offset + 7)
    november_1 = date(year, 11, 1)
    first_sunday_in_november = november_1 + timedelta(days=(6 - november_1.weekday()) % 7)
    return second_sunday_in_march, first_sunday_in_november


def _resolve_timezone(local_tz: str, *, reference: datetime | None = None):
    try:
        return ZoneInfo(local_tz)
    except Exception:
        pass

    if local_tz == "America/New_York":
        ref = reference or datetime.now(timezone.utc)
        dst_start, dst_end = _us_dst_bounds(ref.year)
        offset_hours = -4 if dst_start <= ref.date() < dst_end else -5
        return timezone(timedelta(hours=offset_hours), name="America/New_York")

    system_tz = datetime.now().astimezone().tzinfo
    return system_tz or timezone.utc


def _unfold_ics_lines(ics_text: str) -> list[str]:
    unfolded: list[str] = []
    for raw_line in ics_text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if not raw_line:
            continue
        if raw_line.startswith((" ", "\t")) and unfolded:
            unfolded[-1] += raw_line[1:]
            continue
        unfolded.append(raw_line)
    return unfolded


def _parse_property_line(line: str) -> tuple[str, dict[str, str], str] | None:
    if ":" not in line:
        return None
    head, value = line.split(":", 1)
    parts = head.split(";")
    name = parts[0].upper()
    params: dict[str, str] = {}
    for part in parts[1:]:
        if "=" not in part:
            continue
        key, param_value = part.split("=", 1)
        params[key.upper()] = param_value
    return name, params, value


def _unescape_ics_text(value: str) -> str:
    return (
        value.replace("\\n", "\n")
        .replace("\\N", "\n")
        .replace("\\,", ",")
        .replace("\\;", ";")
        .replace("\\\\", "\\")
    )


def _fallback_attendees_by_title() -> dict[str, list[str]]:
    return {
        event.title.lower(): list(event.attendees)
        for event in SAMPLE_EVENTS
    }


def _display_people_for_event(event: dict[str, object]) -> list[str]:
    organizer = event.get("organizer", {})
    organizer_name = str(organizer.get("name", SYNTHETIC_CALENDAR_OWNER_NAME)).strip()
    organizer_label = f"Organizer: {organizer_name}"
    display_people = [organizer_label]
    for attendee_email in event.get("attendees", []):
        attendee_email = str(attendee_email).strip()
        if not attendee_email:
            continue
        attendee_name = ATTENDEE_NAMES_BY_EMAIL.get(attendee_email.lower())
        if attendee_name:
            display_people.append(f"Attendee: {attendee_name} <{attendee_email}>")
        else:
            display_people.append(f"Attendee: {attendee_email}")
    return display_people


def _parse_datetime_value(
    value: str,
    *,
    tzid: str | None,
    local_tz: str,
    is_end_date_only: bool = False,
) -> datetime:
    value = value.strip()
    if len(value) == 8 and value.isdigit():
        parsed_date = datetime.strptime(value, "%Y%m%d").date()
        if is_end_date_only:
            parsed_date -= timedelta(days=1)
        parsed_dt = datetime.combine(parsed_date, time(0, 0))
        target_tz = _resolve_timezone(local_tz, reference=parsed_dt)
        return parsed_dt.replace(tzinfo=target_tz)

    parsed_formats = ("%Y%m%dT%H%M%SZ", "%Y%m%dT%H%M%S", "%Y%m%dT%H%M")
    parsed_dt: datetime | None = None
    for fmt in parsed_formats:
        try:
            parsed_dt = datetime.strptime(value, fmt)
            break
        except ValueError:
            continue
    if parsed_dt is None:
        raise ValueError(f"Unsupported ICS datetime value: {value}")

    target_tz = _resolve_timezone(local_tz, reference=parsed_dt)
    if value.endswith("Z"):
        parsed_dt = parsed_dt.replace(tzinfo=timezone.utc).astimezone(target_tz)
    elif tzid:
        try:
            parsed_dt = parsed_dt.replace(tzinfo=ZoneInfo(tzid)).astimezone(target_tz)
        except Exception:
            parsed_dt = parsed_dt.replace(tzinfo=target_tz)
    else:
        parsed_dt = parsed_dt.replace(tzinfo=target_tz)
    return parsed_dt


def parse_ics_events(ics_text: str, *, local_tz: str = "America/New_York") -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    fallback_attendees = _fallback_attendees_by_title()
    current: dict[str, object] | None = None
    for line in _unfold_ics_lines(ics_text):
        if line == "BEGIN:VEVENT":
            current = {
                "attendees": [],
                "organizer": {
                    "name": SYNTHETIC_CALENDAR_OWNER_NAME,
                    "email": SYNTHETIC_CALENDAR_OWNER_EMAIL,
                },
            }
            continue
        if line == "END:VEVENT":
            if not current or "start" not in current or "end" not in current:
                current = None
                continue
            start_dt: datetime = current["start"]  # type: ignore[assignment]
            end_dt: datetime = current["end"]  # type: ignore[assignment]
            title = str(current.get("title", "(untitled)"))
            attendee_emails = list(dict.fromkeys(current.get("attendees", [])))  # type: ignore[arg-type]
            if not attendee_emails:
                attendee_emails = fallback_attendees.get(title.lower(), [])
            events.append(
                {
                    "title": title,
                    "start": start_dt.strftime("%Y-%m-%dT%H:%M"),
                    "end": end_dt.strftime("%Y-%m-%dT%H:%M"),
                    "attendees": attendee_emails,
                    "organizer": {
                        "name": str(current.get("organizer", {}).get("name", SYNTHETIC_CALENDAR_OWNER_NAME)).strip()
                        or SYNTHETIC_CALENDAR_OWNER_NAME,
                        "email": "",
                    },
                    "display_people": _display_people_for_event(
                        {
                            "attendees": attendee_emails,
                            "organizer": {
                                "name": str(current.get("organizer", {}).get("name", SYNTHETIC_CALENDAR_OWNER_NAME)).strip()
                                or SYNTHETIC_CALENDAR_OWNER_NAME,
                                "email": "",
                            },
                        }
                    ),
                    "notes": str(current.get("notes", "")),
                }
            )
            current = None
            continue
        if current is None:
            continue

        parsed = _parse_property_line(line)
        if parsed is None:
            continue
        name, params, value = parsed
        if name == "SUMMARY":
            current["title"] = _unescape_ics_text(value)
            continue
        if name == "DESCRIPTION":
            current["notes"] = _unescape_ics_text(value)
            continue
        if name == "ORGANIZER":
            organizer_value = value
            if ":" in organizer_value:
                organizer_value = organizer_value.rsplit(":", 1)[-1]
            organizer_email = organizer_value.removeprefix("mailto:").removeprefix("MAILTO:").strip()
            organizer_name = _unescape_ics_text(params.get("CN", SYNTHETIC_CALENDAR_OWNER_NAME))
            current["organizer"] = {
                "name": organizer_name or SYNTHETIC_CALENDAR_OWNER_NAME,
                "email": organizer_email or SYNTHETIC_CALENDAR_OWNER_EMAIL,
            }
            continue
        if name == "ATTENDEE":
            attendee_value = value
            if ":" in attendee_value:
                attendee_value = attendee_value.rsplit(":", 1)[-1]
            attendee_value = attendee_value.removeprefix("mailto:").removeprefix("MAILTO:")
            attendee_value = attendee_value.strip()
            if attendee_value:
                current.setdefault("attendees", []).append(attendee_value)
            continue
        if name == "DTSTART":
            current["start"] = _parse_datetime_value(
                value,
                tzid=params.get("TZID"),
                local_tz=local_tz,
            )
            continue
        if name == "DTEND":
            current["end"] = _parse_datetime_value(
                value,
                tzid=params.get("TZID"),
                local_tz=local_tz,
                is_end_date_only=("VALUE" in params and params["VALUE"].upper() == "DATE"),
            )
            continue
    return sorted(events, key=lambda event: str(event["start"]))


def _overlaps(start_a: datetime, end_a: datetime, start_b: datetime, end_b: datetime) -> bool:
    return start_a < end_b and start_b < end_a


def _compute_daily_free_windows(day_events: list[dict[str, object]], current_day: date) -> list[str]:
    free_windows: list[str] = []
    for hour in range(9, 17):
        start = datetime.combine(current_day, time(hour, 0))
        end = start + timedelta(hours=1)
        if any(
            _overlaps(
                start,
                end,
                datetime.fromisoformat(str(event["start"])),
                datetime.fromisoformat(str(event["end"])),
            )
            for event in day_events
        ):
            continue
        free_windows.append(f"{start:%Y-%m-%dT%H:%M}-{end:%H:%M}")
    return free_windows


def build_calendar_snapshot(
    events: list[dict[str, object]],
    *,
    days: int = 10,
    start_date: date | None = None,
    local_tz: str = "America/New_York",
) -> dict:
    snapshot_start = start_date or datetime.now(_resolve_timezone(local_tz)).date()
    window_end = snapshot_start + timedelta(days=days)
    filtered_events = [
        event
        for event in events
        if datetime.fromisoformat(str(event["end"])).date() >= snapshot_start
        and datetime.fromisoformat(str(event["start"])).date() < window_end
    ]
    days_payload: list[dict[str, object]] = []
    for offset in range(days):
        current_day = snapshot_start + timedelta(days=offset)
        day_events = [
            event
            for event in filtered_events
            if datetime.fromisoformat(str(event["start"])).date() == current_day
        ]
        day_events = sorted(day_events, key=lambda event: str(event["start"]))
        days_payload.append(
            {
                "date": current_day.isoformat(),
                "weekday": current_day.strftime("%A"),
                "label": current_day.strftime("%a %b %d"),
                "events": day_events,
                "free_windows": _compute_daily_free_windows(day_events, current_day),
            }
        )
    return {
        "source": "published-outlook-ics",
        "generated_at": datetime.now(_resolve_timezone(local_tz)).isoformat(timespec="seconds"),
        "local_timezone": local_tz,
        "window_start": snapshot_start.isoformat(),
        "window_days": days,
        "raw_event_count": len(events),
        "events_in_window": len(filtered_events),
        "days": days_payload,
    }


def render_calendar_snapshot_html(snapshot: dict) -> str:
    day_cards = []
    for day in snapshot["days"]:
        busy_events = "".join(
            """
            <li class="snapshot-event">
              <strong>{title}</strong>
              <span>{start} - {end}</span>
              <span>{attendees}</span>
            </li>
            """.format(
                title=escape(str(event["title"])),
                start=escape(str(event["start"])[11:16]),
                end=escape(str(event["end"])[11:16]),
                attendees="<br />".join(
                    escape(str(person))
                    for person in event.get("display_people", [])
                ),
            )
            for event in day["events"]
        )
        free_windows = "".join(
            f"<li>{escape(str(window))}</li>"
            for window in day["free_windows"]
        )
        if not busy_events:
            busy_events = '<li class="snapshot-empty">No scheduled events captured for this day.</li>'
        if not free_windows:
            free_windows = '<li class="snapshot-empty">No clear 1-hour free windows between 09:00 and 17:00.</li>'
        day_cards.append(
            """
            <section class="snapshot-day">
              <header>
                <p>{weekday}</p>
                <h2>{label}</h2>
              </header>
              <div class="snapshot-columns">
                <div>
                  <h3>Busy events</h3>
                  <ul>{busy_events}</ul>
                </div>
                <div>
                  <h3>Visible free 1-hour windows</h3>
                  <ul>{free_windows}</ul>
                </div>
              </div>
            </section>
            """.format(
                weekday=escape(str(day["weekday"])),
                label=escape(str(day["label"])),
                busy_events=busy_events,
                free_windows=free_windows,
            )
        )

    return """
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>Published Calendar Snapshot</title>
        <style>
          :root {{
            color-scheme: light;
            --bg: #f3f5f8;
            --card: #ffffff;
            --ink: #13233a;
            --muted: #58677b;
            --line: #d5dce4;
            --accent: #0b6aa2;
            --free: #e9f7ef;
          }}
          body {{
            margin: 0;
            background: var(--bg);
            color: var(--ink);
            font: 16px/1.5 "Segoe UI", Arial, sans-serif;
          }}
          .snapshot-shell {{
            max-width: 1200px;
            margin: 0 auto;
            padding: 24px;
          }}
          .snapshot-hero,
          .snapshot-nav,
          .snapshot-day {{
            background: var(--card);
            border: 1px solid var(--line);
            border-radius: 18px;
            padding: 20px;
            margin-bottom: 18px;
            box-shadow: 0 10px 28px rgba(14, 31, 53, 0.06);
          }}
          .snapshot-hero p {{
            margin: 0 0 8px;
            color: var(--muted);
          }}
          .snapshot-nav {{
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
          }}
          .snapshot-nav a {{
            display: inline-flex;
            align-items: center;
            border-radius: 999px;
            padding: 8px 12px;
            background: rgba(11, 106, 162, 0.1);
            border: 1px solid var(--line);
            color: var(--accent);
            text-decoration: none;
          }}
          .snapshot-hero h1 {{
            margin: 0 0 8px;
            font-size: 30px;
          }}
          .snapshot-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 12px;
            margin-top: 14px;
          }}
          .snapshot-grid div {{
            border: 1px solid var(--line);
            border-radius: 12px;
            padding: 12px;
            background: #fafbfd;
          }}
          .snapshot-day header p {{
            margin: 0;
            color: var(--muted);
            text-transform: uppercase;
            letter-spacing: 0.08em;
            font-size: 12px;
          }}
          .snapshot-day header h2 {{
            margin: 4px 0 0;
            font-size: 22px;
          }}
          .snapshot-columns {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 18px;
            margin-top: 16px;
          }}
          .snapshot-columns h3 {{
            margin: 0 0 10px;
            font-size: 15px;
          }}
          .snapshot-columns ul {{
            list-style: none;
            padding: 0;
            margin: 0;
          }}
          .snapshot-event,
          .snapshot-columns li {{
            border: 1px solid var(--line);
            border-radius: 12px;
            padding: 10px 12px;
            margin-bottom: 10px;
            background: #fafbfd;
          }}
          .snapshot-event strong {{
            display: block;
            margin-bottom: 4px;
          }}
          .snapshot-event span {{
            display: block;
            color: var(--muted);
            font-size: 14px;
          }}
          .snapshot-columns div:last-child li {{
            background: var(--free);
          }}
          .snapshot-empty {{
            color: var(--muted);
          }}
          @media (max-width: 860px) {{
            .snapshot-columns {{
              grid-template-columns: 1fr;
            }}
          }}
        </style>
      </head>
      <body>
        <main class="snapshot-shell">
          <section class="snapshot-hero">
            <p>Published Outlook Calendar Snapshot</p>
            <h1>Next {window_days} calendar days</h1>
            <p>
              Generated at {generated_at}. This local mirror is built from the published Outlook ICS feed and can be used
              instead of live Outlook sign-in during BrowserUse runs.
            </p>
            <div class="snapshot-grid">
              <div><strong>Window start</strong><br />{window_start}</div>
              <div><strong>Timezone</strong><br />{local_timezone}</div>
              <div><strong>Raw events parsed</strong><br />{raw_event_count}</div>
              <div><strong>Events in window</strong><br />{events_in_window}</div>
            </div>
          </section>
          {day_cards}
        </main>
      </body>
    </html>
    """.format(
        window_days=escape(str(snapshot["window_days"])),
        generated_at=escape(str(snapshot["generated_at"])),
        window_start=escape(str(snapshot["window_start"])),
        local_timezone=escape(str(snapshot["local_timezone"])),
        raw_event_count=escape(str(snapshot["raw_event_count"])),
        events_in_window=escape(str(snapshot["events_in_window"])),
        day_cards="".join(day_cards),
    )


def refresh_calendar_snapshot_from_ics_url(
    ics_url: str,
    *,
    days: int = 10,
    start_date: date | None = None,
    local_tz: str = "America/New_York",
) -> dict[str, object]:
    ensure_calendar_snapshot_dirs()
    raw_ics = fetch_published_calendar_ics(ics_url)
    events = parse_ics_events(raw_ics, local_tz=local_tz)
    snapshot = build_calendar_snapshot(
        events,
        days=days,
        start_date=start_date,
        local_tz=local_tz,
    )
    html = render_calendar_snapshot_html(snapshot)

    RAW_ICS_PATH.write_text(raw_ics, encoding="utf-8")
    SNAPSHOT_JSON_PATH.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    SNAPSHOT_HTML_PATH.write_text(html, encoding="utf-8")

    return {
        "ics_url": ics_url,
        "raw_ics_path": str(RAW_ICS_PATH.resolve()),
        "snapshot_json_path": str(SNAPSHOT_JSON_PATH.resolve()),
        "snapshot_html_path": str(SNAPSHOT_HTML_PATH.resolve()),
        "events_in_window": snapshot["events_in_window"],
        "window_start": snapshot["window_start"],
        "window_days": snapshot["window_days"],
    }
