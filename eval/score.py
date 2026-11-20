"""Compare the existing rules and evidence-validated Codex cache against gold50.

Offline by default. --codex-run explicitly enables CLI calls for missing samples.
--tag run1/run2 uses independent caches, not the production cache, for replication.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if __package__ in (None, ""):
    sys.path.insert(0, str(ROOT))

from scripts.enrich_with_codex import body, cached_result, enrich_events, load_cache
from scripts.fetch_events import classify, extract_place_time

FIELDS = ("type", "time", "place")


def judge(field: str, prediction: str, gold: dict) -> str:
    expected = gold["place_key" if field == "place" else field]
    prediction = prediction or ""
    if not expected:
        correct = not prediction
    elif field == "place":
        correct = (any(key in prediction.lower() for key in ("온라인", "zoom", "줌"))
                   if expected == "온라인" else expected in prediction)
    else:
        correct = prediction == expected
    if correct:
        return "정답"
    return "비움" if not prediction and expected else "틀림"


def rule_prediction(event: dict) -> dict:
    place, clock = extract_place_time(body(event))
    return {"type": classify(event.get("title", ""), body(event)), "time": clock, "place": place}


def evaluate(samples: list[dict], gold: list[dict], cache: dict) -> tuple[dict, list[dict], int]:
    by_id = {str(event["id"]): event for event in samples}
    counts = {method: {field: Counter({key: 0 for key in ("정답", "비움", "틀림")})
                       for field in FIELDS} for method in ("규칙", "Codex")}
    cases = []
    missing = 0
    for answer in gold:
        event = by_id[str(answer["id"])]
        codex = cached_result(cache, event)
        missing += codex is None
        for method, prediction in (("규칙", rule_prediction(event)), ("Codex", codex or {})):
            for field in FIELDS:
                value = prediction.get(field, "")
                outcome = judge(field, value, answer)
                counts[method][field][outcome] += 1
                if outcome != "정답":
                    cases.append({"method": method, "id": str(answer["id"]), "title": answer.get("title", ""),
                                  "field": field, "outcome": outcome,
                                  "gold": answer["place_key" if field == "place" else field],
                                  "prediction": value,
                                  "missing": method == "Codex" and codex is None})
    return counts, cases, missing


def cell(value) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("|", "\\|").replace("\n", " ").replace("\r", " ") or "(빈칸)"


def write_report(path: Path, samples: list[dict], gold: list[dict], caches: dict[str, dict]) -> None:
    lines = ["# 종류·시간·장소 평가", "", f"정답표: gold50.json, 표본 {len(gold)}건. 규칙은 sample50.json 원문에서 다시 계산.",
             "time은 정확히 일치, place는 place_key 포함 여부(온라인은 온라인/Zoom/줌), gold 빈칸은 예측도 빈칸일 때 정답.",
             "예측이 비어 있고 gold가 있으면 비움, 그 밖의 불일치는 틀림.", ""]
    combined = []
    lines.extend(["| 방식 | 필드 | 정답 | 비움 | 틀림 |", "| --- | --- | ---: | ---: | ---: |"])
    coverages = []
    for index, (label, cache) in enumerate(caches.items()):
        counts, cases, missing = evaluate(samples, gold, cache)
        coverages.append(f"{label}: 캐시 {len(gold) - missing}/{len(gold)}건, 미실행·실패·본문 변경 {missing}건.")
        for method in ("규칙", "Codex"):
            if method == "규칙" and index:
                continue
            display = label if method == "Codex" else method
            for field in FIELDS:
                row = counts[method][field]
                lines.append(f"| {display} | {field} | {row['정답']} | {row['비움']} | {row['틀림']} |")
            combined.extend([{**case, "method": display} for case in cases if case["method"] == method])
    lines.extend(["", *coverages,
                  "캐시에 없는 Codex 예측은 빈 문자열로 집계했다. 따라서 gold가 빈칸인 항목의 정답 수에는 미실행 항목도 포함되며, 실제 Codex 성능은 실행 완료 후 판단해야 한다.",
                  "", "## 틀림·비움 사례", "", "| 방식 | id | 제목 | 필드 | 판정 | gold | 예측 | 비고 |",
                  "| --- | --- | --- | --- | --- | --- | --- | --- |"])
    for case in combined:
        values = [case[key] for key in ("method", "id", "title", "field", "outcome", "gold", "prediction")]
        values.append("캐시 없음" if case["missing"] else "")
        lines.append("| " + " | ".join(map(cell, values)) + " |")
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-run", action="store_true")
    parser.add_argument("--tag", help="Independent run cache/report name, e.g. run1 or run2")
    parser.add_argument("--timeout", type=float, default=300)
    args = parser.parse_args()
    if args.tag and not re.fullmatch(r"[A-Za-z0-9_-]+", args.tag):
        parser.error("--tag must contain only letters, digits, underscores or hyphens")
    samples = json.loads((ROOT / "eval/sample50.json").read_text(encoding="utf-8"))
    gold = json.loads((ROOT / "eval/gold50.json").read_text(encoding="utf-8"))["items"]
    suffix = f".{args.tag}" if args.tag else ""
    cache_path = ROOT / f"data/codex_cache{suffix}.json"
    cache = (enrich_events(samples, cache_path, timeout=args.timeout)[0]
             if args.codex_run else load_cache(cache_path))
    label = f"Codex ({args.tag})" if args.tag else "Codex"
    caches = {label: cache}
    if args.tag:
        write_report(ROOT / f"eval/RESULT{suffix}.md", samples, gold, caches)
        # Keep independent run reports, plus a combined comparison in RESULT.md.
        for tag in ("run1", "run2"):
            other = ROOT / f"data/codex_cache.{tag}.json"
            if tag != args.tag and other.exists():
                caches[f"Codex ({tag})"] = load_cache(other)
    report = ROOT / "eval/RESULT.md"
    write_report(report, samples, gold, caches)
    print(f"Saved {report}")


if __name__ == "__main__":
    main()
