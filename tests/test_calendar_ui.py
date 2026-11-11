"""Exercise the page's actual rendering code offline with Node's VM."""
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("period", ["week", "month", "today", "next", "all"])
def test_period_rendering(period):
    node = shutil.which("node")
    assert node, "Node.js is required for the calendar rendering regression tests"
    page = Path(__file__).resolve().parents[1] / "docs/index.html"
    script = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync(process.argv[1], 'utf8').split('<script>')[1].split('</script>')[0];
const elements = {};
const context = vm.createContext({URL, Intl, Date, document: {
  getElementById: id => elements[id] ||= {}, querySelectorAll: () => []
}});
// Stop before wiring browser listeners and fetching; all render functions stay intact.
vm.runInContext(source.split("document.querySelector('.periods')")[0], context);
vm.runInContext(`
  seoulToday=()=> '2026-11-11';
  state.loaded=true;
  state.period=${JSON.stringify(process.argv[2])};
  state.events=[
    ['monday','2026-11-09','2026-11-09'],
    ['tuesday','2026-11-10','2026-11-10'],
    ['today','2026-11-11','2026-11-11'],
    ['future','2026-11-13','2026-11-13'],
    ['ended','2026-11-01','2026-11-10'],
    ['ongoing','2026-11-01','2026-11-12'],
    ['earlier','2026-11-02','2026-11-02'],
    ['next','2026-11-16','2026-11-16']
  ].map(([title,begin,end])=>({title,begin,end,type:'공연',time:'',url:'https://www.snu.ac.kr/snunow/events'}));
  render();
`, context);
const period = process.argv[2];
const html = elements.list.innerHTML;
if (['week','month'].includes(period)) {
  const [visible, past] = html.split('<details class="past-events">');
  assert.ok(past);
  assert.ok(past.startsWith(`<summary>${period === 'week' ? '이번 주' : '이번 달'} 지난 행사`));
  assert.ok(!html.includes('<details open'));
  for (const title of ['today','future','ongoing']) assert.ok(visible.includes(`>${title}</a>`));
  for (const title of ['monday','tuesday','ended']) {
    assert.ok(!visible.includes(`>${title}</a>`));
    assert.ok(past.includes(`>${title}</a>`));
  }
  assert.ok(visible.indexOf('>today</a>') < visible.indexOf('>future</a>'));
  assert.equal(past.includes('>earlier</a>'), period === 'month');
  assert.equal(elements.count.textContent, period === 'week' ? '6개의 행사' : '8개의 행사');
  // Search/type filters apply to the collapsed portion and total as well.
  vm.runInContext("state.query='monday';render();", context);
  assert.ok(elements.list.innerHTML.includes('>monday</a>'));
  assert.ok(!elements.list.innerHTML.includes('>today</a>'));
  assert.equal(elements.count.textContent, '1개의 행사');
  vm.runInContext("state.query='';state.selected.add('전시');render();", context);
  assert.equal(elements.count.textContent, '0개의 행사');
  // No empty disclosure when every matching event is current or upcoming.
  vm.runInContext("state.selected.clear();state.query='today';render();", context);
  assert.ok(!elements.list.innerHTML.includes('<details'));
} else {
  assert.ok(!html.includes('<details'));
  if (period === 'today') {
    assert.ok(html.includes('>today</a>'));
    assert.ok(html.includes('>ongoing</a>'));
    assert.ok(!html.includes('>monday</a>'));
  }
  if (period === 'next') {
    assert.ok(html.includes('>next</a>'));
    assert.ok(!html.includes('>today</a>'));
  }
  if (period === 'all') assert.ok(html.includes('>monday</a>'));
}
"""
    result = subprocess.run(
        [node, "-e", script, str(page), period], stdin=subprocess.DEVNULL,
        capture_output=True, text=True,
        encoding="utf-8", timeout=20,
    )
    assert result.returncode == 0, result.stderr
