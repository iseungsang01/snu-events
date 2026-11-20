"""RFC 5545 wire-format, publication, and optional independent parser checks."""
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from scripts import build_calendars as feeds
from scripts import fetch_events

ROOT = Path(__file__).resolve().parents[1]
STAMP = datetime.fromisoformat("2026-11-20T06:00:00+09:00")


def event(**changes):
    return {"id": "123", "title": "공연, 특별; 행사\\제목\n다음 줄",
            "begin": "2026-11-20", "end": "2026-11-20", "time": "14:00~16:20",
            "place": "예술관, 콘서트홀; 1층", "summary": "행사 소개\n둘째 줄",
            "url": "https://www.snu.ac.kr/snunow/events?md=v&bbsidx=123", "type": "공연", **changes}


def unfold(data):
    assert data.endswith(b"\r\n")
    assert b"\n" not in data.replace(b"\r\n", b"")
    for line in data.split(b"\r\n"):
        assert len(line) <= 75
        line.decode("utf-8")  # No multibyte character was split by a fold.
    return data.replace(b"\r\n ", b"").decode("utf-8")


@pytest.mark.parametrize("clock,end,start_line,end_line", [
    ("14:00~16:20", "2026-11-20", "DTSTART;TZID=Asia/Seoul:20261120T140000", "DTEND;TZID=Asia/Seoul:20261120T162000"),
    ("23:30", "2026-11-20", "DTSTART;TZID=Asia/Seoul:20261120T233000", "DTEND;TZID=Asia/Seoul:20261121T003000"),
    ("23:30~01:00", "2026-11-20", "DTSTART;TZID=Asia/Seoul:20261120T233000", "DTEND;TZID=Asia/Seoul:20261121T010000"),
    ("", "2026-11-20", "DTSTART;VALUE=DATE:20261120", "DTEND;VALUE=DATE:20261121"),
    ("14:00~16:20", "2026-11-22", "DTSTART;VALUE=DATE:20261120", "DTEND;VALUE=DATE:20261123"),
    ("미정", "2026-11-22", "DTSTART;VALUE=DATE:20261120", "DTEND;VALUE=DATE:20261123"),
])
def test_calendar_dates(clock, end, start_line, end_line):
    text = unfold(feeds.make_calendar([event(time=clock, end=end)], "서울대 행사 — 공연", STAMP))
    assert start_line + "\r\n" in text
    assert end_line + "\r\n" in text
    assert "X-WR-TIMEZONE:Asia/Seoul\r\n" in text
    assert "BEGIN:VTIMEZONE\r\nTZID:Asia/Seoul" in text


def test_wire_format_escaping_folding_and_stable_uid():
    row = event(title=event()["title"] + "한글🙂" * 90)
    raw = feeds.make_calendar([row], "서울대 행사 — 공연", STAMP)
    text = unfold(raw)
    assert b"\r\n " in raw
    assert "SUMMARY:공연\\, 특별\\; 행사\\\\제목\\n다음 줄" in text
    assert "LOCATION:예술관\\, 콘서트홀\\; 1층" in text
    assert "DESCRIPTION:행사 소개 둘째 줄\\n원문: " + row["url"] in text
    assert "URL:" + row["url"] + "\r\n" in text
    assert "DTSTAMP:20261119T210000Z\r\n" in text
    updated = unfold(feeds.make_calendar([dict(row, title="변경", begin="2026-11-21", end="2026-11-21")],
                                         "서울대 행사", STAMP + timedelta(days=1)))
    assert re.findall(r"^UID:.*$", text, re.M) == re.findall(r"^UID:.*$", updated, re.M) == ["UID:123@snu-events\r"]
    injected = unfold(feeds.make_calendar([event(title="제목\r\nBEGIN:VEVENT", place="장소\rATTENDEE:evil")], "전체", STAMP))
    assert injected.count("\r\nBEGIN:VEVENT\r\n") == 1
    assert "\r\nATTENDEE:evil" not in injected


def test_category_files_and_deterministic_rebuild(tmp_path):
    rows = [event(id=str(i), type=label) for i, label in enumerate(feeds.TYPES.values())]
    payload = {"fetched_at": STAMP.isoformat(), "events": rows}
    feeds.write_calendars(payload, tmp_path)
    before = {p.name: p.read_bytes() for p in tmp_path.glob("*.ics")}
    assert set(before) == {"all.ics", *(key + ".ics" for key in feeds.TYPES)}
    assert unfold(before["all.ics"]).count("BEGIN:VEVENT\r\n") == 6
    for i, (key, label) in enumerate(feeds.TYPES.items()):
        text = unfold(before[key + ".ics"])
        assert "X-WR-CALNAME:서울대 행사 — " + label in text
        assert text.count("BEGIN:VEVENT\r\n") == 1
        assert f"UID:{i}@snu-events\r\n" in text
    feeds.write_calendars(payload, tmp_path)
    assert before == {p.name: p.read_bytes() for p in tmp_path.glob("*.ics")}
    feeds.write_calendars({**payload, "events": []}, tmp_path)
    assert all("BEGIN:VEVENT" not in unfold(p.read_bytes()) for p in tmp_path.glob("*.ics"))


def test_fetch_publishes_calendars(monkeypatch, tmp_path):
    monkeypatch.setattr(fetch_events, "fetch_all", lambda today: [{
        "idx": "123", "title": "공연", "begin": "2026-11-20", "end": "2099-11-20"}])
    monkeypatch.setattr("sys.argv", ["fetch", "--output", str(tmp_path / "events.json")])
    fetch_events.main()
    assert len(list((tmp_path / "calendar").glob("*.ics"))) == 7
    assert "UID:123@snu-events" in unfold((tmp_path / "calendar/all.ics").read_bytes())


def test_generated_repository_calendars_match_current_json():
    payload = json.loads((ROOT / "docs/events.json").read_text(encoding="utf-8"))
    expected = {str(row["id"]) + "@snu-events" for row in payload["events"]}
    assert set(re.findall(r"^UID:([^\r]+)", unfold((ROOT / "docs/calendar/all.ics").read_bytes()), re.M)) == expected
    for key, label in feeds.TYPES.items():
        ids = set(re.findall(r"^UID:([^\r]+)", unfold((ROOT / f"docs/calendar/{key}.ics").read_bytes()), re.M))
        assert ids == {str(row["id"]) + "@snu-events" for row in payload["events"] if row["type"] == label}


def test_independent_icalendar_round_trip():
    icalendar = pytest.importorskip("icalendar", reason="Install requirements-dev.txt for independent ICS parsing")
    rows = [event(), event(id="124", time="23:30"), event(id="125", end="2026-11-22")]
    calendar = icalendar.Calendar.from_ical(feeds.make_calendar(rows, "서울대 행사 — 공연", STAMP))
    assert not any(component.errors for component in calendar.walk())
    parsed = calendar.walk("VEVENT")
    assert len(parsed) == 3
    assert str(parsed[0]["SUMMARY"]) == rows[0]["title"]
    assert str(parsed[0]["LOCATION"]) == rows[0]["place"]
    assert str(parsed[0]["URL"]) == rows[0]["url"]
    assert parsed[0].decoded("DTSTART").utcoffset() == timedelta(hours=9)
    assert parsed[1].decoded("DTEND") - parsed[1].decoded("DTSTART") == timedelta(hours=1)
    assert parsed[2].decoded("DTSTART") == date(2026, 11, 20)
    assert parsed[2].decoded("DTEND") == date(2026, 11, 23)
    for path in (ROOT / "docs/calendar").glob("*.ics"):
        parsed_calendar = icalendar.Calendar.from_ical(path.read_bytes())
        assert not any(component.errors for component in parsed_calendar.walk())
