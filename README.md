# 이번 주 서울대 행사 한눈에

[서울대학교 SNU 캘린더](https://www.snu.ac.kr/snunow/events)의 공개 행사를 날짜순으로 모은 정적 웹페이지입니다. 기간(오늘·이번 주·다음 주·이번 달·전체), 여러 종류, 제목·본문 검색을 지원하며 모바일과 시스템 다크 모드에 대응합니다. 외부 프런트엔드 라이브러리는 사용하지 않습니다.

## 로컬 실행

Python 3.10 이상에서 저장소 루트를 기준으로 실행합니다.

```sh
python -m pip install -r requirements-dev.txt
python scripts/fetch_events.py --from-sample reference/sample_raw_events.json
python -m pytest
python -m http.server 8000 --directory docs
```

브라우저에서 <http://localhost:8000>을 엽니다. `index.html`을 직접 열면 브라우저의 파일 보안 정책 때문에 JSON을 읽지 못할 수 있습니다. 실제 공개 목록을 수집하려면 `python scripts/fetch_events.py`를 실행합니다.

## 데이터와 표시 기준

- 날짜는 한국 시간(Asia/Seoul), 주간은 월요일부터 일요일입니다. 선택 기간과 하루라도 겹치는 행사를 보여 줍니다.
- 여러 날 행사는 ‘진행 중 · 기간 행사’에 한 번만 표시하며 현재 날짜에 따라 진행 중·시작 예정·종료를 구분합니다. 등록된 기간이 신청 기간이나 시리즈 전체 기간일 수 있으므로 매일 개최된다는 뜻은 아닙니다.
- 끝난 지 **7일 초과**인 행사는 제외합니다. 날짜를 읽을 수 없는 항목은 제외합니다. `전체`는 수집된 데이터 전체를 의미합니다.
- 제목을 우선하고 본문으로 보완하는 키워드 규칙으로 공연 / 전시 / 대회·공모 / 특강·세미나 / 모집·안내 / 기타를 분류합니다. 학술대회는 특강·세미나로 분류합니다.
- 장소·시간은 본문에 명시된 표기만 추출합니다. 추출하지 못한 값은 빈 문자열이며, 시작·종료 한 쌍은 `18:00~20:50`처럼 적고, 시각이 셋 이상이면 비워 둡니다. 회차별 시간과 휴관일은 원문을 확인하세요.
- 요약은 120자 이내입니다. 요약 및 검색용 본문(`search_text`)은 문의·담당자 구간 이후를 제외하고 전화·이메일을 제거합니다. 이미지 속 정보는 판독하지 않습니다.
- 공개 목록과 상세만 조회합니다. 참고 수집기의 선택자, 0.3초 요청 간격, 5개 연속 오래된 페이지 종료·최대 60페이지, 5xx 재시도(2·4·8초)를 사용합니다. 수집 요청 실패 시 기존 JSON을 보존합니다.

## GitHub Pages

저장소 **Settings → Pages → Source → GitHub Actions**를 선택합니다. `pages.yml`이 `docs/` 폴더만 배포합니다. `.github/workflows/update.yml`은 매일 한국 시간 오전 6시(UTC 전날 21시)에 수집하고 데이터가 바뀌면 커밋합니다. Actions의 **Update SNU events → Run workflow**로 수동 실행할 수도 있습니다. 예약 실행은 GitHub 상황에 따라 지연될 수 있습니다.

수집 워크플로에 저장소 쓰기 권한이 필요합니다. `GITHUB_TOKEN`으로 만든 커밋은 Pages의 브랜치 빌드를 다시 실행하지 않으므로, `pages.yml`은 수집 워크플로 성공 후에도 실행됩니다. 기본 브랜치가 `main`이 아니라면 `pages.yml`의 브랜치 이름을 수정하세요.

행사 정보는 항상 SNU 캘린더 원문이 기준입니다.

## Codex로 원문 읽기와 평가

ChatGPT Edu 계정으로 로그인한 Codex CLI가 PATH에 있는 로컬 PC에서 실행합니다. API 키를 설정하지 않으며 기존 CLI 로그인을 사용합니다.

```sh
python scripts/enrich_with_codex.py
python eval/score.py
python eval/score.py --codex-run --tag run1
python eval/score.py --codex-run --tag run2
```

첫 명령은 `docs/events.json`의 새 행사·변경된 본문을 10건씩 읽고, 검증한 결과를 반영합니다. `data/codex_cache.json`에 id와 제목·본문의 SHA-256 해시를 저장하므로 같은 원문은 다시 보내지 않습니다. 실패·시간 초과인 묶음은 캐시하지 않아 다음 실행에 재시도합니다. `--timeout 300`으로 묶음당 제한 시간을 바꿀 수 있습니다. 성공한 묶음마다 캐시를 저장합니다.

Codex는 임시 디렉터리에서 `codex exec --sandbox read-only`와 JSON 스키마를 사용합니다. 원문은 stdin으로 전달하고, 최종 JSON만 `--output-last-message`로 읽습니다. [OpenAI 공식 문서](https://learn.chatgpt.com/docs/non-interactive-mode)의 CLI 규격을 따릅니다. 인용이 공백을 정규화한 원문에 없거나 시각과 불일치하면 해당 값을 비웁니다. 장소의 URL·이메일·전화번호도 거부하며, 실행 끝에 버린 필드 수를 출력합니다. Codex가 읽은 행사는 `source: "codex"`와 `evidence`를, 실패하거나 읽지 않은 행사는 기존 규칙 값과 `source: "rule"`을 갖습니다.

`score.py`는 기본적으로 오프라인 채점만 합니다. 실제 Codex 호출은 `--codex-run`을 명시했을 때만 수행합니다. `--tag run1`과 `--tag run2`는 각각 독립된 `data/codex_cache.run1.json`, `data/codex_cache.run2.json`을 사용하므로 서로의 답을 재사용하지 않습니다. 같은 tag로 다시 실행하면 해당 실행의 미완료 표본만 재시도합니다. 결과는 `eval/RESULT.md`에, tag별 결과는 `eval/RESULT.run1.md` 등에 보존합니다. 기본 평가 캐시는 운영 캐시이며, tag 평가 캐시는 운영 데이터에 반영하지 않습니다. 캐시가 없는 표본은 보고서에 명시하므로 실행 전 수치를 Codex 성능으로 해석하지 마세요.

카드의 시간·장소 근거를 누르면 원문 구절을 볼 수 있습니다. 각 카드의 ‘캘린더에 추가’는 `.ics`를 내려받습니다. 시각은 한국 시간으로, 시간이 없으면 종일 일정으로 내보내고 종일 일정의 마지막 날도 포함합니다. 시작 시각만 있으면 종료 시각을 만들어 넣지 않습니다. 기간 행사는 표시된 시작·종료 날짜를 사용하며, 회차별 반복 일정은 만들지 않습니다.

`scripts/update_local.cmd`는 수집 → Codex 보강 → 커밋·푸시 순으로 실행하며, 보강이 실패해도 수집 결과는 게시합니다. 테스트는 실제 Codex나 네트워크 없이 실행합니다.
