"""Generate subscribable calendars from the same events JSON used by the page."""
from __future__ import annotations

import argparse
import json
import re
from itertools import combinations
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEOUL = timezone(timedelta(hours=9), "Asia/Seoul")
TYPES = {
    "performance": "공연", "exhibition": "전시", "contest": "대회·공모",
    "lecture": "특강·세미나", "recruit": "모집·안내", "other": "기타",
}
TIME = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d(?:~(?:[01]\d|2[0-3]):[0-5]\d)?\Z")


def escape_text(value: str) -> str:
    return (str(value).replace("\\", "\\\\").replace("\r\n", "\n").replace("\r", "\n")
            .replace("\n", "\\n").replace(";", "\\;").replace(",", "\\,"))


def fold_line(line: str) -> str:
    """Fold at UTF-8 character boundaries, counting the continuation space."""
    parts, current, size = [], "", 0
    for character in line:
        width = len(character.encode("utf-8"))
        if size + width > 75:
            parts.append(current)
            current, size = " ", 1
        current += character
        size += width
    return "\r\n".join([*parts, current])


def make_calendar(events: list[dict], name: str, stamp: datetime) -> bytes:
    # Seoul has used UTC+09:00 without daylight saving since October 1988.
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//SNU Events//Campus Calendar//KO",
             "CALSCALE:GREGORIAN", "X-WR-CALNAME:" + escape_text(name), "X-WR-TIMEZONE:Asia/Seoul",
             "BEGIN:VTIMEZONE", "TZID:Asia/Seoul", "BEGIN:STANDARD", "DTSTART:19881009T030000",
             "TZOFFSETFROM:+1000", "TZOFFSETTO:+0900", "TZNAME:KST", "END:STANDARD", "END:VTIMEZONE"]
    for row in events:
        lines.extend(["BEGIN:VEVENT", "UID:" + escape_text(f"{row['id']}@snu-events"),
                      "DTSTAMP:" + stamp.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")])
        begin, end = date.fromisoformat(row["begin"]), date.fromisoformat(row["end"])
        clock = row.get("time", "")
        if begin == end and TIME.fullmatch(clock):
            times = clock.split("~")
            start = datetime.combine(begin, datetime.strptime(times[0], "%H:%M").time(), SEOUL)
            if len(times) == 2:
                finish = datetime.combine(end, datetime.strptime(times[1], "%H:%M").time(), SEOUL)
                if finish <= start:
                    finish += timedelta(days=1)
            else:
                finish = start + timedelta(hours=1)
        else:
            start, finish = begin, end + timedelta(days=1)
        for key, value in [("DTSTART", start), ("DTEND", finish)]:
            if isinstance(value, datetime):
                lines.append(f"{key};TZID=Asia/Seoul:" + value.strftime("%Y%m%dT%H%M%S"))
            else:
                lines.append(f"{key};VALUE=DATE:" + value.strftime("%Y%m%d"))
        description = "\n".join(filter(None, [
            " ".join(row.get("summary", "").split()), "원문: " + row["url"]]))
        lines.extend(["SUMMARY:" + escape_text(row["title"]),
                      "LOCATION:" + escape_text(row.get("place", "")),
                      "DESCRIPTION:" + escape_text(description),
                      "URL:" + row["url"].replace("\r", "").replace("\n", ""), "END:VEVENT"])
    lines.append("END:VCALENDAR")
    return ("\r\n".join(map(fold_line, lines)) + "\r\n").encode("utf-8")


def write_calendars(payload: dict, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    # Rebuilding unchanged input is deterministic, including DTSTAMP.
    stamp = datetime.fromisoformat(payload["fetched_at"])
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=SEOUL)
    events = payload["events"]
    feeds = {"all": ("전체", events)}
    for key, label in TYPES.items():
        feeds[key] = (label, [row for row in events if (
            row.get("type") == label or key == "other" and row.get("type") not in TYPES.values())])
    # Every nonempty subset has one stable, alphabetically sorted address.
    (output / "mix").mkdir(exist_ok=True)
    for size in range(1, len(TYPES) + 1):
        for keys in combinations(sorted(TYPES), size):
            labels = {TYPES[key] for key in keys}
            name = "all" if size == len(TYPES) else "-".join(keys)
            rows = [row for row in events if row.get("type") in labels or (
                "other" in keys and row.get("type") not in TYPES.values())]
            feeds[f"mix/{name}"] = (" · ".join(TYPES[key] for key in keys), rows)
    for key, (label, rows) in feeds.items():
        target = output / f"{key}.ics"
        temporary = target.with_suffix(".ics.tmp")
        temporary.write_bytes(make_calendar(rows, f"서울대 행사 — {label}", stamp))
        temporary.replace(target)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=Path, default=ROOT / "docs/events.json")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.events.read_text(encoding="utf-8"))
    output = args.output or args.events.parent / "calendar"
    write_calendars(payload, output)
    print(f"Saved 7 category calendars and 63 combinations ({len(payload['events'])} events) to {output}")


if __name__ == "__main__":
    main()
