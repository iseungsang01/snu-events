"""Exercise list/detail retries and publication without network access or waits."""
import json
from unittest.mock import Mock

import pytest
import requests

from scripts import fetch_events


@pytest.mark.parametrize("error_type", [
    requests.ConnectionError,
    requests.Timeout,
    requests.exceptions.ChunkedEncodingError,
])
@pytest.mark.parametrize("stage", ["list", "detail"])
@pytest.mark.parametrize("recover", [True, False], ids=["recover", "exhaust"])
def test_transport_retries_and_publication(monkeypatch, tmp_path, error_type, stage, recover):
    output = tmp_path / "events.json"
    original = b'{"events": [], "fetched_at": "previous"}\n'
    output.write_bytes(original)
    monkeypatch.setattr("sys.argv", ["fetch_events.py", "--output", str(output)])
    waits = []
    monkeypatch.setattr(fetch_events.time, "sleep", waits.append)
    monkeypatch.setattr(fetch_events, "REQUEST_INTERVAL", 0)

    session = Mock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(fetch_events.requests, "Session", lambda: session)
    error = error_type("Response ended prematurely")
    attempts = []

    def respond(url, *, params, timeout):
        assert url == fetch_events.LIST_URL
        assert timeout == 30
        is_detail = params.get("md") == "v"
        if (stage == "detail" and is_detail) or (stage == "list" and params.get("page") == 2):
            attempts.append(params.copy())
            if not recover or len(attempts) < 4:
                raise error
        response = requests.Response()
        response.status_code = 200
        if is_detail:
            html = '<div class="view"><div class="content">Event details</div></div>'
        elif params["page"] == 1:
            html = '''<div class="board-imgline"><a class="item" href="?bbsidx=123">
                <span class="title">Event</span><span class="sub">
                <span class="point">2099.11.11</span></span></a></div>'''
        else:
            html = "<div></div>"
        response._content = html.encode("utf-8")
        return response

    session.get.side_effect = respond
    if recover:
        fetch_events.main()
        events = json.loads(output.read_text(encoding="utf-8"))["events"]
        assert len(events) == 1
        assert events[0]["id"] == "123"
        assert events[0]["search_text"] == "Event details"
    else:
        with pytest.raises(error_type) as caught:
            fetch_events.main()
        assert caught.value is error
        assert output.read_bytes() == original
        assert not output.with_suffix(".json.tmp").exists()

    expected_params = {"md": "v", "bbsidx": "123"} if stage == "detail" else {"page": 2}
    assert attempts == [expected_params] * 4
    assert [wait for wait in waits if wait] == [2, 4, 8]
