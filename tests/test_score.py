import json

import pytest

from eval import score
from scripts.enrich_with_codex import body_hash


@pytest.mark.parametrize("field,prediction,gold,expected", [
    ("time", "14:00", {"time": "14:00"}, "정답"),
    ("time", "14:00~16:00", {"time": "14:00"}, "틀림"),
    ("time", "", {"time": "14:00"}, "비움"),
    ("time", "", {"time": ""}, "정답"),
    ("time", "14:00", {"time": ""}, "틀림"),
    ("place", "서울대학교 38동 429호", {"place_key": "38동 429호"}, "정답"),
    ("place", "38동 428호", {"place_key": "38동 429호"}, "틀림"),
    ("place", "", {"place_key": "홀"}, "비움"),
    ("place", "", {"place_key": ""}, "정답"),
    ("place", "홀", {"place_key": ""}, "틀림"),
    ("place", "온라인(Zoom)", {"place_key": "온라인"}, "정답"),
    ("place", "ZOOM", {"place_key": "온라인"}, "정답"),
    ("place", "줌 화상회의", {"place_key": "온라인"}, "정답"),
    ("place", "대면 강의실", {"place_key": "온라인"}, "틀림"),
    ("type", "공연", {"type": "공연"}, "정답"),
    ("type", "전시", {"type": "공연"}, "틀림"),
    ("type", "", {"type": "공연"}, "비움"),
])
def test_judging(field, prediction, gold, expected):
    assert score.judge(field, prediction, gold) == expected


def test_recompute_rules_and_missing_cache_report(tmp_path):
    samples = [{"id": "1", "title": "특강", "search_text": "일시: 14:00 장소: 예술관 콘서트홀",
                "type": "전시", "time": "wrong", "place": "wrong"}]
    gold = [{"id": "1", "title": "특강", "type": "특강·세미나", "time": "14:00", "place_key": "콘서트홀"}]
    cache = {"events": {}}
    counts, cases, missing = score.evaluate(samples, gold, cache)
    assert missing == 1
    assert all(counts["규칙"][field]["정답"] == 1 for field in score.FIELDS)
    assert all(counts["Codex"][field]["비움"] == 1 for field in score.FIELDS)
    assert all(case["missing"] for case in cases)
    path = tmp_path / "RESULT.md"
    score.write_report(path, samples, gold, {"Codex": cache})
    report = path.read_text(encoding="utf-8")
    assert "캐시 0/1건" in report
    assert "| 규칙 | time | 1 | 0 | 0 |" in report


def test_tag_runs_use_independent_caches(tmp_path, monkeypatch):
    (tmp_path / "eval").mkdir()
    sample = {"id": "1", "title": "특강", "search_text": "14:00"}
    (tmp_path / "eval/sample50.json").write_text(json.dumps([sample]), encoding="utf-8")
    (tmp_path / "eval/gold50.json").write_text(json.dumps({"items": [
        {"id": "1", "type": "특강·세미나", "time": "14:00", "place_key": ""}]}), encoding="utf-8")
    monkeypatch.setattr(score, "ROOT", tmp_path)
    paths = []
    def fake(samples, path, **kwargs):
        paths.append(path.name)
        return {"events": {"1": {"body_hash": body_hash(sample), "result": {
            "type": "특강·세미나", "time": "14:00", "time_quote": "14:00", "place": "", "place_quote": ""}}}}, {}
    monkeypatch.setattr(score, "enrich_events", fake)
    for tag in ("run1", "run2"):
        monkeypatch.setattr("sys.argv", ["score", "--codex-run", "--tag", tag])
        score.main()
        assert (tmp_path / f"eval/RESULT.{tag}.md").exists()
    assert paths == ["codex_cache.run1.json", "codex_cache.run2.json"]
