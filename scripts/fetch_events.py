"""Fetch the public SNU calendar, or transform the supplied raw JSON offline."""
from __future__ import annotations

import argparse
import json
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
LIST_URL = "https://www.snu.ac.kr/snunow/events"
KST = timezone(timedelta(hours=9), "Asia/Seoul")
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"}
STALE_PAGES, MAX_PAGES = 5, 60
REQUEST_INTERVAL = 0.3
DATE = re.compile(r"(\d{4})\s*[.년/-]\s*(\d{1,2})\s*[.월/-]\s*(\d{1,2})")
BBS_IDX = re.compile(r"bbsidx=(\d+)")


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def parse_dates(text: str) -> tuple[str, str]:
    """Return ISO dates; a single day has identical start and end dates."""
    found = []
    for parts in DATE.findall(text or ""):
        try:
            found.append(date(*map(int, parts)).isoformat())
        except ValueError:
            return "", ""
    if not found or found[-1] < found[0]:
        return "", ""
    return found[0], found[-1]


def iso_date(value: str) -> str:
    try:
        return date.fromisoformat(value or "").isoformat()
    except ValueError:
        return ""


def parse_list(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for a in soup.select("div.board-imgline a.item"):
        match = BBS_IDX.search(a.get("href", ""))
        if not match:
            continue
        sub = a.select_one("span.sub")
        point = sub.select_one("span.point") if sub else None
        period = clean(point.get_text(" ")) if point else ""
        if point:
            point.extract()
        begin, end = parse_dates(period)
        title = a.select_one("span.title")
        rows.append({"idx": match[1], "title": clean(title.get_text(" ")) if title else "",
                     "period": period, "begin": begin, "end": end,
                     "desc": clean(sub.get_text(" ")) if sub else ""})
    return rows


def parse_detail(html: str) -> dict:
    body = BeautifulSoup(html, "html.parser").select_one("div.view div.content")
    return {"content": clean(body.get_text(" "))[:4000] if body else ""}


def get(session: requests.Session, *, params: dict, tries: int = 4):
    """Retry transient HTTP/transport failures after 2/4/8 seconds, never 4xx."""
    for attempt in range(1, tries + 1):
        try:
            response = session.get(LIST_URL, params=params, timeout=30)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            retryable = isinstance(exc, (requests.Timeout, requests.ConnectionError,
                                        requests.exceptions.ChunkedEncodingError)) or (
                exc.response is not None and exc.response.status_code in {500, 502, 503, 504})
            if not retryable or attempt == tries:
                raise
            time.sleep(2.0 ** attempt)


def fetch_all(today: date) -> list[dict]:
    cutoff = (today - timedelta(days=7)).isoformat()
    events = {}
    stale = 0
    with requests.Session() as session:
        session.headers.update(HEADERS)
        for page in range(1, MAX_PAGES + 1):
            response = get(session, params={"page": page})
            rows = parse_list(response.text)
            if not rows:
                # Do not overwrite the last good data after a markup change/error page.
                if page == 1:
                    raise RuntimeError("공개 목록을 찾지 못했습니다. 페이지 구조를 확인하세요.")
                break
            live = [r for r in rows if r["end"] and r["end"] >= cutoff]
            for row in live:
                events[row["idx"]] = row
            stale = 0 if live else stale + 1
            print(f"page {page}: {len(live)} retained, {len(events)} total")
            time.sleep(REQUEST_INTERVAL)
            if stale >= STALE_PAGES:
                break
        # Any request failure aborts publication, preserving the previous complete file.
        for idx, row in events.items():
            row.update(parse_detail(get(session, params={"md": "v", "bbsidx": idx}).text))
            time.sleep(REQUEST_INTERVAL)
    return list(events.values())


RULES = (
    ("대회·공모", r"경진대회|공모|해커톤|아이디어톤|챌린지|체육대회|분석대회|capstone\s+challenge"),
    ("공연", r"공연|콘서트|음악회|연주회|상영회|오케스트라|symphony|orchestra|concert"),
    ("전시", r"전시|특별전|기획전|기념전|exhibition"),
    ("특강·세미나", r"특강|세미나|강연|강좌|콜로[퀴키][움엄]|컬로[퀴키][움엄]|심포지[엄움]|포럼|학술대회|워크[숍샵]|북토크|웨비나|대담|라운드테이블|seminar|lecture|colloquium|symposium|conference|workshop|\btalks?\b"),
    ("모집·안내", r"모집|채용|설명회|신청|접종|안내|참가|상담"),
)


def classify(title: str, content: str = "") -> str:
    # A specific title beats incidental words in a long body (e.g. an exhibition's lecture).
    for text in (title, content):
        for kind, pattern in RULES:
            if re.search(pattern, text, re.I):
                return kind
    return "기타"


CONTACT = re.compile(r"문의(?:처|사항)?|담당(?:자|직원|교직원)?|연락처|연락\s*전화|contact\s*[:：]", re.I)
EMAIL = re.compile(r"[\w.+-]+\s*@\s*[\w.-]+\s*\.\s*[A-Za-z]{2,}")
PHONE = re.compile(
    r"(?<!\d)(?:(?:\+82[- .]?)?0?\d{1,3}[- .)]\s*\d{3,4}[- .]\d{4}|"
    r"(?:01[016789]\d{7,8}|02\d{7,8}))(?!\d)")


def public_text(text: str) -> str:
    # Drop the entire contact tail before truncation so staff names cannot survive alone.
    text = re.sub(r"[가-힣A-Za-z]{2,20}\s*\(?\s*(?=담당자|담당직원|담당교직원)", "", text or "")
    text = CONTACT.split(text, maxsplit=1)[0]
    text = EMAIL.sub("", text)
    text = PHONE.sub("", text)
    return clean(text)


# Label boundaries also work on the reference parser's flattened body text.
BOUNDARY = re.compile(
    r"(?:[□■○●◆▶※*•]|\n|\s[-–]+\s(?!\d)|\s+l\s|\s(?:일\s*시|장\s*소|시\s*간|일정|일자|기간|제목|"
    r"신청(?:\s*마감|\s*방법|\s*기간)?|사전신청(?:\([^)]*\))?|주\s*제|대상|참가대상|교육분야|발표자?|강연자?|강사|연사|사회자?|토론|주최|후원|"
    r"문의(?:처)?|담당자|티켓|관람료|사업내용|개막식|참여작가|온라인\s*사전등록|행사\s*안내\s*및\s*사전등록)\s*[:：|])")
CLOCK = re.compile(
    r"(?<![\d:])(?P<prefix>오전|오후)?\s*"
    r"(?P<hour>[01]?\d|2[0-3])"
    r"(?::(?P<minute>[0-5]\d)(?!\d)|\s*시(?:\s*(?P<kminute>[0-5]?\d)\s*분)?)"
    r"\s*(?P<suffix>[ap]\.?m\.?)?", re.I)


def extract_time(scope: str) -> str:
    # Expand Korean shorthand so all clock formats are counted together.
    scope = re.sub(r"(?<![\d:.])(\d{1,2})(\s*[~–-]\s*(?:오전\s*|오후\s*)?\d{1,2}\s*시)",
                   r"\1시\2", scope)
    matches = list(CLOCK.finditer(scope))
    if not 1 <= len(matches) <= 2:
        return ""
    markers = [m["prefix"] or (m["suffix"] or "").lower().replace(".", "") for m in matches]
    if len(matches) == 2 and re.fullmatch(r"\s*[~–-]\s*", scope[matches[0].end():matches[1].start()]):
        # A shared meridiem applies only across an explicit range.
        markers = [markers[0] or markers[1], markers[1] or markers[0]]
    times = []
    for match, marker in zip(matches, markers):
        hour = int(match["hour"])
        if marker:
            if not 1 <= hour <= 12:
                return ""
            hour = hour % 12 + (12 if marker in {"오후", "pm"} else 0)
        minute = int(match["minute"] or match["kminute"] or 0)
        times.append(f"{hour:02d}:{minute:02d}")
    return "~".join(times)


def label_value(content: str, label: str) -> str:
    match = re.search(label + r"\s*[:：|]\s*", content)
    return BOUNDARY.split(content[match.end():], maxsplit=1)[0].strip(" ,-•") if match else ""


def extract_place_time(content: str) -> tuple[str, str]:
    place = label_value(content, r"장\s*소")
    if not place:
        # Only an explicit building / room token; never infer a campus from an organizer.
        match = re.search(r"\d{1,3}(?:-\d+)?\s*동(?:\s*\d+\s*층)?(?:\s*\d+(?:-\d+)?\s*호)?", content)
        place = match[0] if match else ""
    scope = label_value(content, r"(?:관람\s*시간|운영\s*시간|일\s*시(?:\s*\(기간\))?|시\s*간)")
    # Without a time label, discard deadline/contact clauses before looking for a clock.
    if not scope:
        scope = re.split(r"신청\s*마감|제출\s*마감|접수\s*마감|문의|담당", content, maxsplit=1)[0]
    return clean(place), extract_time(scope)


def transform(raw_events: list[dict], today: date) -> list[dict]:
    cutoff = (today - timedelta(days=7)).isoformat()
    events = {}
    for raw in raw_events:
        begin, end = iso_date(raw.get("begin", "")), iso_date(raw.get("end", ""))
        if not begin or not end:
            begin, end = parse_dates(raw.get("period", ""))
        if not begin or not end or end < begin or end < cutoff:
            continue
        idx = str(raw.get("idx", ""))
        if not idx.isdigit():
            continue
        title, content = clean(raw.get("title", "")), raw.get("content", "") or ""
        place, clock = extract_place_time(content)
        events[idx] = {
            "id": idx, "title": title, "begin": begin, "end": end,
            "summary": public_text(raw.get("desc") or content)[:120],
            "url": f"{LIST_URL}?md=v&bbsidx={idx}",
            "type": classify(title, content), "place": place, "time": clock,
            "search_text": public_text(content),
        }
    return sorted(events.values(), key=lambda e: (e["begin"], e["end"], e["id"]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-sample", type=Path, help="원시 JSON을 네트워크 없이 변환")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/events.json")
    args = parser.parse_args()
    now = datetime.now(KST)
    if args.from_sample:
        raw = json.loads(args.from_sample.read_text(encoding="utf-8"))
    else:
        raw = fetch_all(now.date())
    payload = {"fetched_at": now.isoformat(timespec="seconds"), "events": transform(raw, now.date())}
    if args.from_sample:
        payload["sample_source"] = "2026-10-26"  # Disclose that this is a historical snapshot.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    print(f"Saved {len(payload['events'])} events to {args.output}")


if __name__ == "__main__":
    main()
