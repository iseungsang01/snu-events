"""Every model call in these tests is a fake; no CLI or network is used."""
import json
from pathlib import Path
import subprocess

import pytest

from scripts import enrich_with_codex as enrich

CALL_CODEX = enrich.call_codex


@pytest.fixture(autouse=True)
def prohibit_real_codex(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("A real Codex call is forbidden in tests")
    monkeypatch.setattr(enrich, "call_codex", forbidden)


def event(idx="1", text="오후 2시 (약 2시간 20분), 장소: 예술관 콘서트홀"):
    return {"id": idx, "title": "음악회", "search_text": text, "type": "공연",
            "time": "14:00~02:00", "place": "규칙 장소"}


def prediction(idx="1", **changes):
    return {"id": idx, "type": "공연", "time": "14:00", "time_quote": "오후 2시",
            "place": "예술관 콘서트홀", "place_quote": "예술관 콘서트홀", **changes}


@pytest.mark.parametrize("field,changes", [
    ("time", {"time_quote": "오후 3시"}),
    ("place", {"place_quote": "없는 장소"}),
    ("time", {"time": "15:00"}),
    ("time", {"time": "14:00~02:00", "time_quote": "오후 2시 (약 2시간 20분)"}),
    ("time", {"time": "14:00~16:20", "time_quote": "오후 2시 (약 2시간 20분)"}),
    ("time", {"time": "24:00"}),
    ("time", {"time": "2:00"}),
    ("time", {"time_quote": "   "}),
])
def test_reject_unsupported_value(field, changes):
    result, dropped = enrich.validate_result(event(), prediction(**changes))
    assert result[field] == result[field + "_quote"] == ""
    assert dropped[field] == 1
    assert sum(dropped.values()) == 1


@pytest.mark.parametrize("contact", ["https://zoom.us/j/123", "www.snu.ac.kr", "zoom.us/j/123",
                                      "staff@snu.ac.kr", "staff @ snu.ac.kr", "02-880-1234", "01012345678", "1588-1234",
                                      "0318801234", "07012345678", "15881234", "(02) 880-1234"])
def test_reject_place_with_contacts(contact):
    place = "예술관 콘서트홀 " + contact
    result, dropped = enrich.validate_result(event(text=place), prediction(time="", time_quote="", place=place))
    assert result["place"] == result["place_quote"] == ""
    assert dropped["place"] == 1


@pytest.mark.parametrize("quote,clock", [
    ("오후 2시", "14:00"), ("오전 12시", "00:00"), ("오후 12시", "12:00"),
    ("오후 2시 20분", "14:20"), ("오후 2시 반", "14:30"),
    ("오후 2~4시", "14:00~16:00"), ("오후 2시~4시", "14:00~16:00"),
    ("14~16:00", "14:00~16:00"), ("2:30 p.m.", "14:30"),
    ("18:00 ~ 20:50", "18:00~20:50"),
])
def test_supported_clock_notations(quote, clock):
    result, dropped = enrich.validate_result(event(text=quote), prediction(time=clock, time_quote=quote, place="", place_quote=""))
    assert result["time"] == clock
    assert not dropped


def test_quote_normalizes_only_whitespace():
    row = event(text="오후\n2시 장소: 예술관\u00a0  콘서트홀")
    result, dropped = enrich.validate_result(row, prediction())
    assert not dropped
    assert result["place_quote"] == "예술관 콘서트홀"


def test_online_and_empty_values():
    result, dropped = enrich.validate_result(event(text="Zoom 온라인 진행"), prediction(
        time="", time_quote="없는 구절", place="온라인(Zoom)", place_quote="Zoom 온라인 진행"))
    assert result["place"] == "온라인(Zoom)"
    assert result["time_quote"] == ""
    assert not dropped


def test_cache_batches_edits_and_application(tmp_path):
    rows = [event(str(i)) for i in range(23)]
    calls = []
    def fake(batch, **kwargs):
        calls.append([row["id"] for row in batch])
        return [prediction(row["id"]) for row in reversed(batch)]
    path = tmp_path / "cache.json"
    cache, stats = enrich.enrich_events(rows, path, runner=fake)
    assert list(map(len, calls)) == [10, 10, 3]
    assert stats["read"] == 23
    enrich.apply_results(rows, cache)
    assert all(row["source"] == "codex" and row["time"] == "14:00" for row in rows)
    assert rows[0]["evidence"]["time_quote"] == "오후 2시"
    cache, stats = enrich.enrich_events(rows, path)
    assert stats["cached"] == 23
    assert stats["read"] == 0
    rows[0]["search_text"] += " 본문 변경"
    rows[1]["title"] += " 제목 변경"
    cache, stats = enrich.enrich_events(rows, path, runner=fake)
    assert calls[-1] == ["0", "1"]
    assert stats["read"] == 2
    assert enrich.load_cache(path) == cache


@pytest.mark.parametrize("exception", [subprocess.TimeoutExpired("fake", 1), OSError("failure"), ValueError("bad JSON"), RuntimeError("codex exited 1")])
def test_failed_batch_does_not_block_later_and_retries(tmp_path, exception):
    rows = [event(str(i)) for i in range(11)]
    def fake(batch, **kwargs):
        if batch[0]["id"] == "0":
            raise exception
        return [prediction(row["id"]) for row in batch]
    path = tmp_path / "cache.json"
    cache, stats = enrich.enrich_events(rows, path, runner=fake)
    assert stats["failed"] == 10
    assert set(cache["events"]) == {"10"}
    enrich.apply_results(rows, cache)
    assert all(row["source"] == "rule" and row["place"] == "규칙 장소" for row in rows[:10])
    assert rows[10]["source"] == "codex"
    retry = []
    def success(batch, **kwargs):
        retry.extend(row["id"] for row in batch)
        return [prediction(row["id"]) for row in batch]
    _, stats = enrich.enrich_events(rows, path, runner=success)
    assert retry == [str(i) for i in range(10)]
    assert stats["cached"] == 1


def test_changed_body_failed_call_reverts_old_codex_values(tmp_path):
    row = event()
    cache, _ = enrich.enrich_events([row], tmp_path / "cache.json", runner=lambda *a, **k: [prediction()])
    enrich.apply_results([row], cache)
    row["search_text"] = "일시: 19:00 장소: 101동 210호"
    enrich.apply_results([row], cache)
    assert row["source"] == "rule"
    assert row["time"] == "19:00"
    assert row["place"] == "101동 210호"
    assert "evidence" not in row


def test_rejected_value_is_empty_codex_value_and_counted(tmp_path, capsys):
    row = event()
    cache, stats = enrich.enrich_events([row], tmp_path / "cache.json", runner=lambda *a, **k: [prediction(time="16:00")])
    enrich.apply_results([row], cache)
    assert stats["time"] == 1
    assert row["source"] == "codex"
    assert row["time"] == row["evidence"]["time_quote"] == ""
    assert "discarded=1" in capsys.readouterr().out


@pytest.mark.parametrize("response", [[], [prediction(), prediction()], [prediction("wrong")], [prediction(type="포럼")], [{}]])
def test_invalid_batch_never_cached(tmp_path, response):
    path = tmp_path / "cache.json"
    cache, stats = enrich.enrich_events([event()], path, runner=lambda *a, **k: response)
    assert stats["failed"] == 1
    assert not cache["events"]
    assert not path.exists()


def test_cli_transport_is_readonly_schema_json_and_stdin(monkeypatch):
    seen = {}
    monkeypatch.setattr(enrich.shutil, "which", lambda name: "fake-codex")
    class FakeProcess:
        returncode = 0
        def __init__(self, command, **kwargs):
            seen["command"] = command
            seen["kwargs"] = kwargs
            schema = json.loads(Path(command[command.index("--output-schema") + 1]).read_text(encoding="utf-8"))
            assert schema["additionalProperties"] is False
            output = Path(command[command.index("--output-last-message") + 1])
            output.write_text(json.dumps({"events": [prediction()]}), encoding="utf-8")
        def communicate(self, prompt, timeout):
            seen["prompt"] = prompt
            return "unrelated progress, not JSON", ""
    monkeypatch.setattr(enrich.subprocess, "Popen", FakeProcess)
    assert CALL_CODEX([event()]) == [prediction()]
    assert seen["command"][1:4] == ["exec", "--sandbox", "read-only"]
    assert 'approval_policy="never"' in seen["command"]
    assert seen["command"][-1] == "-"
    assert event()["search_text"] in seen["prompt"]
    assert seen["kwargs"]["cwd"] != enrich.ROOT


def test_main_writes_rule_fallback_even_when_calls_fail(tmp_path, monkeypatch):
    path, cache = tmp_path / "events.json", tmp_path / "cache.json"
    path.write_text(json.dumps({"events": [event()], "fetched_at": "keep"}), encoding="utf-8")
    def failure(*args, **kwargs):
        raise FileNotFoundError("CLI missing")
    monkeypatch.setattr(enrich, "call_codex", failure)
    monkeypatch.setattr("sys.argv", ["enrich", "--events", str(path), "--cache", str(cache)])
    with pytest.raises(SystemExit, match="1"):
        enrich.main()
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["fetched_at"] == "keep"
    assert saved["events"][0]["source"] == "rule"
    assert saved["events"][0]["place"] == "규칙 장소"


@pytest.mark.parametrize("mode", ["nonzero", "timeout", "json"])
def test_cli_transport_errors(monkeypatch, mode):
    monkeypatch.setattr(enrich.shutil, "which", lambda name: "fake-codex")
    killed = []
    class FakeProcess:
        pid = 999999
        returncode = 1 if mode == "nonzero" else 0
        def __init__(self, command, **kwargs):
            output = Path(command[command.index("--output-last-message") + 1])
            output.write_text("not JSON", encoding="utf-8")
        def communicate(self, prompt=None, timeout=None):
            if mode == "timeout" and prompt is not None:
                raise subprocess.TimeoutExpired("fake", timeout)
            return "", "CLI failure"
        def kill(self):
            killed.append(True)
    monkeypatch.setattr(enrich.subprocess, "Popen", FakeProcess)
    monkeypatch.setattr(enrich.subprocess, "run", lambda *a, **k: None)
    monkeypatch.setattr(enrich.os, "killpg", lambda *a: None, raising=False)
    exception = {"nonzero": RuntimeError, "timeout": subprocess.TimeoutExpired, "json": ValueError}[mode]
    with pytest.raises(exception):
        CALL_CODEX([event()])
    assert bool(killed) == (mode == "timeout")
