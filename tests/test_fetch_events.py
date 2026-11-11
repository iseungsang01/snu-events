import json
from datetime import date, timedelta
from pathlib import Path

import pytest
import requests

from scripts.fetch_events import (
    classify, extract_place_time, get, parse_dates, parse_detail, parse_list,
    public_text, transform,
)

SAMPLE = json.loads((Path(__file__).resolve().parents[1] / "reference/sample_raw_events.json").read_text(encoding="utf-8"))
BY_ID = {row["idx"]: row for row in SAMPLE}


@pytest.mark.parametrize("text,expected", [
    ("2026.09.28.(월) ~ 2026.10.18.(일)", ("2026-09-28", "2026-10-18")),
    ("2026.11.11.(수)", ("2026-11-11", "2026-11-11")),
    ("2026. 11. 5.(목)", ("2026-11-05", "2026-11-05")),
    ("2026년 11월 5일", ("2026-11-05", "2026-11-05")),
    ("2026.02.30", ("", "")), ("일정 미정", ("", "")),
    ("2026.11.12 ~ 2026.11.11", ("", "")),
])
def test_parse_dates(text, expected):
    assert parse_dates(text) == expected


def test_sample_dates():
    assert len(SAMPLE) == 101
    for row in SAMPLE:
        begin, end = parse_dates(row["period"])
        assert begin.replace("-", "") == row["begin"]
        assert end.replace("-", "") == row["end"]


@pytest.mark.parametrize("idx,kind", [
    ("177773", "공연"), ("174158", "공연"), ("174821", "전시"),
    ("174155", "전시"), ("176861", "전시"), ("177686", "대회·공모"),
    ("177476", "대회·공모"), ("176558", "대회·공모"),
    ("177989", "특강·세미나"), ("176921", "특강·세미나"),
    ("177386", "특강·세미나"), ("177662", "모집·안내"),
    ("177908", "모집·안내"),
])
def test_sample_classification(idx, kind):
    row = BY_ID[idx]
    assert classify(row["title"], row["content"]) == kind


def test_body_fallback_and_title_priority():
    assert classify("함께하는 하루", "작은 음악회에 초대합니다") == "공연"
    assert classify("미술관 전시 안내", "연계 특강 및 참가자 모집") == "전시"
    assert classify("학술대회 안내") == "특강·세미나"
    assert classify("함께하는 하루") == "기타"


@pytest.mark.parametrize("idx,place,clock", [
    ("177989", "101동 210호 (아시아연구소 영원홀)", "12:00"),
    ("177920", "관악캠퍼스 61동 320호", "10:30~11:45"),
    ("174821", "서울대학교미술관 2~3F 전시실 1~4", "10:00~18:00"),
    ("176861", "62동(중앙도서관 본관) 4층 로비 내 전시 공간", ""),
    ("177932", "인문대학 6동 403호 철학사상연구소", "16:30~18:30"),
    ("174503", "서울대학교 38동 429호", "18:00~20:50"),
    ("177662", "", ""),
])
def test_sample_place_time(idx, place, clock):
    assert extract_place_time(BY_ID[idx]["content"]) == (place, clock)


@pytest.mark.parametrize("content,expected", [
    ("101동 210호에서 14:00에 만나요", ("101동 210호", "14:00")),
    ("장소: 온라인 Zoom 일시: 2026.11.11 14:00~16:00 문의: 담당자", ("온라인 Zoom", "14:00~16:00")),
    ("장소 | 강당 일시 | 오후 4–6시", ("강당", "16:00~18:00")),
    ("온라인 행사입니다", ("", "")),
    ("접수 마감: 2026.11.11 23:59", ("", "")),
    ("특강이 있습니다. 문의 02-880-1234", ("", "")),
])
def test_explicit_only(content, expected):
    assert extract_place_time(content) == expected


@pytest.mark.parametrize("content,clock", [
    ("18:00 / 20:50", "18:00~20:50"),
    ("10:00 / 23:59 / 13:50 / 15:30", ""),
    ("14:00, 15:00, 16:00", ""),
    ("14:00, 14:00, 14:00", ""),
    ("오후 2시~4시", "14:00~16:00"),
    ("오후 2시 30분~4시 5분", "14:30~16:05"),
    ("7:30PM", "19:30"),
    ("7:30PM / 7:00PM", "19:30~19:00"),
    ("7:30~9:00 p.m.", "19:30~21:00"),
    ("오전 12시~오후 12시", "00:00~12:00"),
    ("오후 2:00~4:00", "14:00~16:00"),
    ("오후 2시, 15:00, 7:30PM", ""),
    ("14:00 / 오후 4시", "14:00~16:00"),
    ("일시: 14:00~16:00 신청 마감: 23:59", "14:00~16:00"),
    ("시간 미정", ""),
])
def test_normalized_and_ambiguous_times(content, clock):
    assert extract_place_time(content)[1] == clock


def test_transform_uses_normalized_time():
    row = {**BY_ID["177989"], "content": "장소: 강당 일시: 오후 2시~4시"}
    assert transform([row], date(2026, 10, 26))[0]["time"] == "14:00~16:00"


def test_retention_sample_boundary():
    # 11/4 is exactly 7 days before 11/11: keep it, discard 11/3.
    events = transform(SAMPLE, date(2026, 11, 11))
    ids = {e["id"] for e in events}
    assert "177902" in ids  # 11/4
    assert "177839" not in ids  # 11/3
    assert "174149" in ids  # multi-day, ended 11/7
    assert "176327" in ids  # extends to 2027 despite a July start
    assert len(events) == 49
    assert events == sorted(events, key=lambda e: (e["begin"], e["end"], e["id"]))
    for event in events:
        assert date.fromisoformat(event["end"]) >= date(2026, 11, 11) - timedelta(days=7)
        assert len(event["summary"]) <= 120
        assert event["url"].endswith("bbsidx=" + event["id"])
        assert "@" not in event["summary"]


def test_missing_invalid_dates_and_duplicates():
    row = BY_ID["177989"]
    events = transform([row, row, {**row, "idx": "999", "begin": "", "end": "", "period": "미정"}], date(2026, 10, 26))
    assert len(events) == 1
    fallback = transform([{**row, "begin": "", "end": ""}], date(2026, 10, 26))
    assert fallback[0]["begin"] == "2026-11-12"


@pytest.mark.parametrize("text", [
    "행사 소개. 문의: 홍길동 02-880-1234 staff@snu.ac.kr",
    "행사 소개. 담당자 이름: 홍길동 연락처: 010-1234-5678",
    "행사 소개. 문의처 홍길동",
    "행사 소개. Contact: 홍길동",
    "행사 소개. 홍길동 담당자 010-1234-5678",
])
def test_summary_removes_contact_names(text):
    assert public_text(text) == "행사 소개."


def test_bare_contact_and_truncation():
    text = public_text("행사 소개 staff @ snu.ac.kr 02 880 1234 010-1234-5678 02)880-1234 01012345678")
    assert text == "행사 소개"
    row = {**BY_ID["177989"], "desc": "가" * 121 + " 문의: 홍길동"}
    assert len(transform([row], date(2026, 10, 26))[0]["summary"]) == 120


def test_reference_html_selectors():
    html = '''<div class="board-imgline"><a class="item" href="?md=v&amp;bbsidx=123">
    <span class="title"> 테스트 행사 </span><span class="sub"><span class="point">2026.11.11.(수)</span> 소개 </span></a></div>'''
    assert parse_list(html) == [{"idx": "123", "title": "테스트 행사", "period": "2026.11.11.(수)",
                                 "begin": "2026-11-11", "end": "2026-11-11", "desc": "소개"}]
    assert parse_detail('<div class="view"><div class="content"> 장소: <b>101동</b> </div></div>') == {"content": "장소: 101동"}
    assert parse_detail("<div>unrelated</div>") == {"content": ""}


def test_retry_keeps_reference_backoff(monkeypatch):
    responses = []
    for status in (503, 502, 200):
        r = requests.Response()
        r.status_code = status
        responses.append(r)
    session = requests.Session()
    monkeypatch.setattr(session, "get", lambda *a, **k: responses.pop(0))
    waits = []
    monkeypatch.setattr("scripts.fetch_events.time.sleep", waits.append)
    assert get(session, params={"page": 1}).status_code == 200
    assert waits == [2, 4]


def test_no_retry_for_private_or_rate_limited_page(monkeypatch):
    session = requests.Session()
    for status in (403, 429):
        response = requests.Response()
        response.status_code = status
        monkeypatch.setattr(session, "get", lambda *a, **k: response)
        with pytest.raises(requests.HTTPError):
            get(session, params={"page": 1})
