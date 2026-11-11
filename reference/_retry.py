"""일시적 네트워크 오류에 대한 재시도.

공공 API 는 페이지를 수십 번 넘기다 보면 중간에 한 번씩 500 을 뱉는다.
재시도가 없으면 그 페이지에서 예외가 올라가 소스가 통째로 실패하고,
**이미 받아둔 페이지까지 함께 버려진다**. 2026-07-28 주간 스캔에서
온통청년이 page 16, K-Startup 이 page 88 에서 이렇게 날아갔다.

4xx 는 요청 자체가 잘못된 것이라 다시 보내도 결과가 같으므로 재시도하지 않는다.
인증키 오류(401/403)를 재시도하면 진단만 느려진다.
"""

from __future__ import annotations

import time

import requests

# 429 는 일부러 뺐다. data.go.kr 은 일일 호출 한도를 넘겼을 때 429 에
# "API token quota exceeded" 를 실어 보내는데, 이건 기다린다고 풀리지 않는다
# (자정에 초기화된다). 재시도하면 남은 한도만 두 배로 태운다.
# 호출부가 429 를 직접 보고 '한도 소진'으로 처리해야 한다.
RETRYABLE_STATUS = {500, 502, 503, 504}
TRIES = 4            # 최초 1회 + 재시도 3회
BACKOFF_BASE = 2.0   # 2초 → 4초 → 8초


def get(
    session: requests.Session,
    url: str,
    *,
    params: dict,
    timeout: float,
    tries: int = TRIES,
    label: str = "",
    verbose: bool = True,
) -> requests.Response:
    """5xx·429·타임아웃·연결 끊김에 한해 지수 백오프로 재시도한 응답.

    끝내 실패하면 마지막 예외를 그대로 올린다. 호출부가 '부분 결과라도
    저장할지'를 판단해야 하므로 예외를 삼키지 않는다.

    tries 는 낮출 수 있게 열어둔다. 페이지네이션은 페이지 수가 수십이라
    넉넉히 기다려도 되지만, 레코드마다 한 번씩 부르는 상세조회는 건수가
    천 단위라 같은 인내심을 적용하면 수집 시간이 몇 시간으로 불어난다.
    """
    last: Exception | None = None

    for attempt in range(1, tries + 1):
        try:
            resp = session.get(url, params=params, timeout=timeout)
        except (requests.Timeout, requests.ConnectionError) as exc:
            last = exc
        else:
            if resp.status_code not in RETRYABLE_STATUS:
                return resp
            last = requests.HTTPError(
                f"HTTP {resp.status_code} for url: {resp.url}", response=resp)

        if attempt == tries:
            break
        wait = BACKOFF_BASE ** attempt
        if verbose:
            print(f"{label} {last} — {wait:.0f}초 후 재시도 ({attempt}/{tries - 1})")
        time.sleep(wait)

    raise last
