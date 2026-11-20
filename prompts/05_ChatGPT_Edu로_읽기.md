# 요청: 종류·시간·장소를 ChatGPT Edu Codex가 원문 근거와 함께 읽게 하고, 규칙과 채점하기

지금 `type`, `time`, `place` 는 키워드·정규식 규칙으로 뽑는다. 원문 50건을 사람이 대조해 정답표를 만들어 뒀어: `eval/gold50.json`
(표본 원문은 `eval/sample50.json`). 규칙이 틀리는 예: "오후 2시 (약 2시간 20분)" → `14:00~02:00`, 모집 공고 본문의 "20:00" 을 행사 시간으로,
포럼을 모집·안내로 분류, 원문에 "예술관 콘서트홀"이 있는데 장소를 비움.

## 만들 것

1. `scripts/enrich_with_codex.py`
   - `docs/events.json` 을 읽고, 아직 읽지 않았거나 본문이 바뀐 행사만(id + 본문 해시로 캐시, `data/codex_cache.json`) 10건씩 묶어
     `codex exec` 를 읽기 전용 샌드박스로 불러 JSON 으로 받는다. 나는 ChatGPT Edu 계정으로 로그인한 codex CLI 를 쓴다.
   - 행사마다 받는 값: `type`(공연/전시/대회·공모/특강·세미나/모집·안내/기타 중 하나), `time`(24시간제 `HH:MM` 또는 `HH:MM~HH:MM`),
     `place`, 그리고 `time_quote`, `place_quote` — 그 값을 뽑은 **원문 그대로의 구절**.
   - 지시문 규칙: 원문에 없으면 빈 문자열. 회차·그룹마다 시간이나 장소가 다르면 빈 문자열. 신청 마감 시각·접수 시간은 행사 시간이 아니다.
     온라인만이면 place 는 "온라인(Zoom)"처럼. 추측 금지.
   - **코드에서 검증**: quote 가 공백을 정규화한 원문의 부분 문자열이 아니면 그 값을 버린다. time 의 시각 숫자가 quote 안에 없으면 버린다.
     place 에 URL·이메일·전화번호가 있으면 버린다. 검증에서 버린 수를 실행 끝에 출력.
   - 결과를 `docs/events.json` 의 각 행사에 반영: `type`, `time`, `place` 는 Codex 값(검증 통과분)으로, `evidence` 에 quote 두 개, `source: "codex"`.
     Codex 가 실패하거나 아직 안 읽은 행사는 지금 규칙 값을 그대로 두고 `source: "rule"`.
   - 호출 실패·시간 초과는 그 묶음만 건너뛰고 다음 실행에 다시 시도.
2. `eval/score.py`
   - `eval/gold50.json` 기준으로 두 방식을 채점: ① 지금 규칙(`scripts/fetch_events.py` 의 함수로 `sample50.json` 원문에서 다시 계산),
     ② Codex(`data/codex_cache.json` 에서 같은 id).
   - 필드별로 정답 / 비움 / 틀림 을 센다. time 은 정확히 같아야 정답. place 는 gold `place_key` 가 예측에 들어 있으면 정답
     (gold 가 "온라인"이면 예측에 온라인·Zoom·줌 중 하나), gold 가 빈칸이면 예측도 빈칸이어야 정답. 예측이 빈칸인데 gold 가 있으면 비움.
   - `--codex-run` 옵션: 캐시에 없는 표본을 `enrich_with_codex.py` 와 같은 함수로 실제 Codex 에 보내 채운다(두 번 돌려 재현성 확인용 `--tag run1/run2` 저장).
   - 결과를 `eval/RESULT.md` 에 표로 쓴다(방식 × 필드 × 정답/비움/틀림, 틀린 사례 목록).
3. `docs/index.html`
   - 카드의 시간·장소 옆에 작은 "근거" 표시: 누르면 원문 구절(quote)이 펼쳐진다. `source` 가 rule 이면 표시하지 않는다.
   - 카드마다 "캘린더에 추가" 버튼: 날짜·시간(있으면)·장소·원문 링크로 `.ics` 를 내려받는다. 시간이 없으면 종일 일정.
4. `scripts/update_local.cmd`: 수집 뒤 `enrich_with_codex.py` 를 돌리고 나서 커밋. enrich 가 실패해도 수집 결과는 올린다.
5. 테스트: codex 호출은 가짜로 바꿔 네트워크 없이 — 인용 검증(원문에 없는 quote 버림, 시각 불일치 버림, 연락처 버림), 캐시, 채점 규칙, ics 생성.

## 지켜 줘

- 이 샌드박스 안에서 실제 `codex exec` 를 부르지 마. 실제 호출은 내가 밖에서 돌릴게. 어떤 명령으로 돌리면 되는지 알려 줘.
- `reference/`, `prompts/`, `eval/gold50.json`, `eval/sample50.json` 은 건드리지 마.
- 다 하면 pytest 결과를 알려 줘.
