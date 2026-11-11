"""서울대학교 SNU 캘린더(www.snu.ac.kr/snunow/events) 수집기.

비교과 시스템과 겹칠 것 같지만 실제로는 거의 안 겹친다. 2026-10 기준 행사
120건을 비교과 74건·학과 공지 290건과 제목으로 대조했더니 같은 행사는 6건(5%)
뿐이었다. 비교과는 **신청형 프로그램**, 캘린더는 연구소·단과대가 여는 **행사
안내**를 그대로 올리는 곳이라 성격이 다르다.

이 소스는 두 갈래로 쓰인다.

  - **지원금** — 대부분은 세미나·콜로키움이라 금액이 없어 `require_amount` 에서
    자연히 빠진다. 남는 것은 연구소 어학연수 장학금, 필드워크 팀 공모, 해커톤
    상금처럼 학과 공지에도 비교과에도 안 올라오는 것들이다.
  - **가볼 만한 행사** — 돈과 무관하게 공연·전시·해커톤·특강 같은 것을 따로
    추린다(`highlights`). 리포트 맨 아래 별도 섹션으로 나간다.

인증키·로그인·대기열 모두 없다. 목록이 `?page=N` 으로 그냥 넘어간다.
"""

from __future__ import annotations

import re
import time
from datetime import date, timedelta

import requests
from bs4 import BeautifulSoup

from . import _retry

BASE = "https://www.snu.ac.kr"
LIST_URL = f"{BASE}/snunow/events"

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"),
}

# 목록은 등록순이라 오래 걸리는 행사(7월 등록, 내년 8월까지)가 20페이지 뒤에도
# 섞여 나온다. 그래서 '한 페이지가 전부 끝난 행사'에서 바로 멈추지 않고, 그런
# 페이지가 연달아 나올 때 멈춘다. 2026-10 실측으로 26페이지에 진행 중 4건이 있었고
# 28페이지부터는 끝까지 0건이었다.
STALE_PAGES = 5
MAX_PAGES = 60

BBS_IDX = re.compile(r"bbsidx=(\d+)")
DATE = re.compile(r"(\d{4})\.(\d{2})\.(\d{2})")


class SnuEventsError(RuntimeError):
    pass


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def _dates(text: str) -> tuple[str, str]:
    """'2026.09.28.(월) ~ 2026.10.18.(일)' → 시작·종료. 하루짜리는 둘 다 그날."""
    found = ["".join(d) for d in DATE.findall(text or "")]
    if not found:
        return "", ""
    return found[0], found[-1]


def _parse_list(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for a in soup.select("div.board-imgline a.item"):
        m = BBS_IDX.search(a.get("href", ""))
        if not m:
            continue
        sub = a.select_one("span.sub")
        point = sub.select_one("span.point") if sub else None
        period = _clean(point.get_text(" ")) if point else ""
        if point:
            point.extract()
        begin, end = _dates(period)
        rows.append({
            "idx": m.group(1),
            "title": _clean(a.select_one("span.title").get_text(" ")) if a.select_one("span.title") else "",
            "period": period,
            "begin": begin,
            "end": end,
            "desc": _clean(sub.get_text(" ")) if sub else "",
        })
    return rows


def _parse_detail(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    body = soup.select_one("div.view div.content")
    return {"content": _clean(body.get_text(" "))[:4000] if body else ""}


def probe() -> tuple[bool, str]:
    resp = requests.get(LIST_URL, headers=HEADERS, timeout=25)
    if resp.status_code != 200:
        return False, f"HTTP {resp.status_code} · {resp.url}"
    if not _parse_list(resp.text):
        return False, "목록 카드를 못 찾음 — 페이지 구조가 바뀌었을 수 있습니다"
    return True, "정상 (인증키 불필요)"


def fetch_all(api_key: str | None = None, *, verbose: bool = True,
              today: date | None = None, details: bool = True,
              sleep: float = 0.3) -> list[dict]:
    """아직 안 끝난 행사 전량. 끝난 행사는 리포트에 쓸 데가 없어 받지 않는다."""
    today_s = (today or date.today()).strftime("%Y%m%d")
    session = requests.Session()
    session.headers.update(HEADERS)
    events: dict[str, dict] = {}
    stale = 0

    for page in range(1, MAX_PAGES + 1):
        try:
            resp = _retry.get(session, LIST_URL, params={"page": page}, timeout=30,
                              label=f"[snu_events] page {page}", verbose=verbose)
        except requests.RequestException as exc:
            if events:
                print(f"[snu_events] 경고: page {page} 에서 중단 ({exc}). "
                      f"받은 {len(events):,}건만 사용합니다.")
                break
            raise SnuEventsError(f"목록 수집 실패 (page={page}): {exc}") from exc

        rows = _parse_list(resp.text)
        if not rows:
            break
        live = [r for r in rows if r["end"] and r["end"] >= today_s and r["idx"] not in events]
        for r in live:
            events[r["idx"]] = r
        stale = 0 if live else stale + 1
        if verbose:
            print(f"[snu_events] page {page}: 진행 중 +{len(live)} (누적 {len(events)})")
        if stale >= STALE_PAGES:
            break
        time.sleep(sleep)

    if details:
        failed = 0
        for idx, row in events.items():
            try:
                resp = _retry.get(session, LIST_URL, params={"md": "v", "bbsidx": idx},
                                  timeout=30, tries=2, label=f"[snu_events] {idx}",
                                  verbose=verbose)
                row.update(_parse_detail(resp.text))
            except requests.RequestException:
                failed += 1
            time.sleep(sleep)
        if failed:
            print(f"[snu_events] 경고: 상세 조회 {failed}건 실패 — 목록 요약만으로 처리합니다.")

    return list(events.values())


# ------------------------------------------------------------------ normalize

# 제목 앞 `[국가미래전략원]` 같은 주최 배지
HOST = re.compile(r"^\s*\[([^\]]{1,20})\]")


def normalize(raw: dict) -> dict:
    idx = str(raw.get("idx") or "")
    url = f"{LIST_URL}?md=v&bbsidx={idx}"
    title = raw.get("title") or ""
    host = HOST.match(title)
    content = raw.get("content") or ""
    return {
        "source": "snu_events",
        "id": f"SNU-EVENT-{idx}",
        "is_personal": True,
        "user_type": "개인 신청 가능",
        "kind": None,
        "title": title,
        "summary": raw.get("desc") or content,
        "support": content or raw.get("desc") or "",
        "category_l": "행사",
        "category_m": "",
        "keywords": "",
        "agency": "서울대학교",
        "operator": host.group(1) if host else "",
        "apply_url": url,
        "ref_url": url,
        "apply_method": "SNU 캘린더 원문의 안내를 따름",
        "screening": "",
        "documents": "",
        "etc": raw.get("period") or "",
        "period_type": "",
        # 모집 공고는 이 기간이 접수기간이고, 행사 안내는 행사일이다. 어느 쪽이든
        # 끝나면 쓸모없어지므로 마감 판정에 그대로 쓴다.
        "apply_begin": raw.get("begin") or "",
        "apply_end": raw.get("end") or "",
        # 교내 행사는 연령·소득·전공을 걸지 않는다. 학부 전용 같은 제한은 본문에만
        # 있어 코드로 못 옮기므로 제한없음으로 두고 판정은 원문 확인에 맡긴다.
        "age_min": "", "age_max": "", "age_unrestricted": "Y",
        "school_cd": "0049010",
        "major_cd": "0011009",
        "job_cd": "0013010",
        "special_cd": "0014010",
        "marriage_cd": "0055003",
        "income_cd": "0043001",
        "income_min": "", "income_max": "", "income_etc": "",
        "zip_cd": "",
        "addition": "",
        "_raw": raw,
    }


# ------------------------------------------------------------------ 가볼 만한 행사

# 보러 가는 것 — 공연·전시·대회·체험·대중 강연. 제목에 이게 있으면 고른다.
FUN = re.compile(
    r"공연|콘서트|음악|연주|전시|초대전|기념전|영화|상영|시네|cine|축제|페스티벌|festival|예술주간|"
    r"해커톤|경진대회|공모전|챌린지|challenge|캠프|파티|체험|공개행사|천체|천문|체육대회|"
    r"특강|토크|talk|탐사|투어|숲|해피 ?아워|happy hour|북 ?콘서트|저자",
    re.IGNORECASE)

# 모집·행정성 안내. 재미와 무관해서 키워드가 걸려도 뺀다.
CHORE = re.compile(
    r"채용|진입생|연합전공|연계전공|최고경영자|전문가 과정|훈련생|연구장비|수합|공청회|이용교육|"
    r"정책평가단|베타테스터|조교 모집|운영조교")

# 참석하면 받는 것. 세미나·설명회라도 이게 있으면 고른다.
# 상품·쿠폰은 어디서 하든 받으면 그만이지만, 먹을 것은 관악에서 할 때만 갈 만하다.
GIFT = re.compile(r"쿠폰|기프티콘|기프트\s*카드|상품권|경품|굿즈|기념품|크레딧")
MEAL = re.compile(r"식사|도시락|다과|간식|샌드위치|피자|음료|커피")
# 관악캠퍼스 장소 표기 — 건물 번호('58동 131호', '62-1동')가 거의 항상 붙는다.
ON_CAMPUS = re.compile(r"관악|\d{1,3}(?:-\d)?동\b|관정|하이플렉스|HyFlex", re.IGNORECASE)


def _perks(text: str) -> list[str]:
    found = sorted({m.group(0) for m in GIFT.finditer(text)})
    if ON_CAMPUS.search(text):
        found += sorted({m.group(0) for m in MEAL.finditer(text)})
    return found


def highlights(policies: list[dict], profile: dict, today: date) -> list[dict]:
    """SNU 캘린더 중 가볼 만한 행사. 앞으로 `horizon_days` 안에 열리는 것만.

    세미나·콜로키움은 기본으로 빼되, 프로필 `events.keywords`(AI·양자 등)가 제목에
    걸리면 살린다 — 전공 밖 학술 행사는 재미가 없지만 관심 분야 특강은 다르다.
    상품·쿠폰을 주거나 관악에서 식사·간식을 주는 행사는 종류와 상관없이 살린다.
    """
    cfg = profile.get("events") or {}
    horizon = (today + timedelta(days=int(cfg.get("horizon_days", 30)))).strftime("%Y%m%d")
    today_s = today.strftime("%Y%m%d")
    keywords = [str(k).strip() for k in cfg.get("keywords") or [] if str(k).strip()]
    # 영문 약어는 단어 경계를 본다. 그냥 부분 문자열로 찾으면 'AI'가 'Grain'에 걸린다.
    # 한글은 조사가 바로 붙으므로('AI와', '양자컴퓨터') 영문 글자만 경계로 친다.
    patterns = {k: re.compile(rf"(?<![A-Za-z]){re.escape(k)}(?![A-Za-z])", re.IGNORECASE)
                for k in keywords}

    picked = []
    for p in policies:
        if p.get("source") != "snu_events":
            continue
        begin, end = p.get("apply_begin") or "", p.get("apply_end") or ""
        if not end or end < today_s or (begin and begin > horizon):
            continue
        title = p.get("title") or ""
        perks = _perks(" ".join(str(p.get(k) or "") for k in ("title", "summary", "support")))
        hits = [k for k, pat in patterns.items() if pat.search(title)]
        if not perks and (CHORE.search(title) or not (FUN.search(title) or hits)):
            continue
        picked.append({**p, "_event_hits": hits, "_event_perks": perks})
    picked.sort(key=lambda p: (p.get("apply_begin") or "", p.get("apply_end") or ""))
    return picked
