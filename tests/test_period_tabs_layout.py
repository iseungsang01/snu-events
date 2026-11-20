"""Static regression checks for the narrow-screen period navigation."""
import re
from pathlib import Path


def test_mobile_period_tabs_wrap_without_horizontal_scrolling():
    page = (Path(__file__).resolve().parents[1] / "docs/index.html").read_text(
        encoding="utf-8"
    )
    css = page.split("<style>", 1)[1].split("</style>", 1)[0]
    mobile = re.search(
        r"@media\s*\(\s*max-width\s*:\s*640px\s*\)\s*"
        r"\{((?:[^{}]|\{[^{}]*\})*)\}",
        css,
    )
    assert mobile, "Keep the wrapping override scoped to narrow screens"
    periods = re.search(r"\.periods\s*\{([^{}]*)\}", mobile[1])
    assert periods
    declarations = dict(
        (name.strip(), value.strip())
        for name, value in re.findall(r"([\w-]+)\s*:\s*([^;{}]+)", periods[1])
    )
    assert declarations.get("flex-wrap") == "wrap"
    assert declarations.get("overflow") == "visible"
    assert declarations.get("overflow-x", "visible") == "visible"

    navigation = re.search(r'<nav class="periods"[^>]*>(.*?)</nav>', page, re.S)
    assert navigation
    assert len(re.findall(r"<button\b", navigation[1])) == 7
    assert 'data-period="all"' in navigation[1]
    assert 'data-period="me"' in navigation[1]
    assert 'id="trash-open"' in navigation[1]
