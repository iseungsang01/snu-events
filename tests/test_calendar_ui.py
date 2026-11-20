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


def test_evidence_and_calendar_download():
    node = shutil.which("node")
    assert node, "Node.js is required for calendar tests"
    page = Path(__file__).resolve().parents[1] / "docs/index.html"
    script = r"""
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(process.argv[1],'utf8').split('<script>')[1].split('</script>')[0];
let blob,clicked=false,removed=false,appended=false,revoked=false;
const link={click(){clicked=true},remove(){removed=true}};
class TestURL extends URL {
  static createObjectURL(value){blob=value;return 'blob:calendar'}
  static revokeObjectURL(value){assert.equal(value,'blob:calendar');revoked=true}
}
const context=vm.createContext({URL:TestURL,Intl,Date,TextEncoder,Blob,
  setTimeout(callback){callback()},document:{createElement(){return link},body:{appendChild(){appended=true}}}});
vm.runInContext(source.split("document.querySelector('.periods')")[0],context);
const event={id:'123',title:'공연, 특별; 행사\\제목\n다음 줄',begin:'2026-11-20',end:'2026-11-20',
  time:'14:00~16:20',place:'예술관 콘서트홀',type:'공연',url:'https://www.snu.ac.kr/snunow/events?bbsidx=123',
  source:'codex',evidence:{time_quote:'오후 2시 <안내>',place_quote:'예술관 콘서트홀'}};
context.event=event;
const evaluate=code=>vm.runInContext(code,context);
const unfold=ics=>ics.replace(/\r\n /g,'');
const timed=unfold(evaluate('makeIcs(event,new Date("2026-11-01T00:00:00Z"))'));
assert.ok(timed.includes('DTSTART:20261120T050000Z\r\n'));
assert.ok(timed.includes('DTEND:20261120T072000Z\r\n'));
assert.ok(timed.includes('DTSTAMP:20261101T000000Z'));
assert.ok(timed.includes('LOCATION:예술관 콘서트홀'));
assert.ok(timed.includes('URL:'+event.url));
assert.ok(timed.includes('DESCRIPTION:원문: '+event.url));
assert.ok(timed.includes('SUMMARY:공연\\, 특별\\; 행사\\\\제목\\n다음 줄'));
assert.ok(timed.endsWith('END:VCALENDAR\r\n'));
assert.ok(!timed.replace(/\r\n/g,'').includes('\n'));
const html=evaluate('card(event,"2026-11-20")');
assert.equal((html.match(/class="evidence"/g)||[]).length,2);
assert.ok(html.includes('오후 2시 &lt;안내&gt;'));
assert.ok(html.includes('data-calendar-id="123"'));
assert.ok(!html.includes('<details open'));
event.source='rule';assert.ok(!evaluate('card(event,"2026-11-20")').includes('class="evidence"'));
event.time='';event.end='2026-11-22';
const allDay=unfold(evaluate('makeIcs(event)'));
assert.ok(allDay.includes('DTSTART;VALUE=DATE:20261120'));
assert.ok(allDay.includes('DTEND;VALUE=DATE:20261123'));
event.end=event.begin;event.time='23:30~01:00';
const overnight=unfold(evaluate('makeIcs(event)'));
assert.ok(overnight.includes('DTSTART:20261120T143000Z'));
assert.ok(overnight.includes('DTEND:20261120T160000Z'));
event.time='00:30';const single=unfold(evaluate('makeIcs(event)'));
assert.ok(single.includes('DTSTART:20261119T153000Z'));
assert.ok(!single.includes('DTEND'));
event.time='14:00~16:00';event.end='2026-11-22';
assert.ok(unfold(evaluate('makeIcs(event)')).includes('DTEND:20261122T070000Z'));
event.title='가나다😀'.repeat(80);
const folded=evaluate('makeIcs(event)');
for(const line of folded.split('\r\n'))assert.ok(Buffer.byteLength(line,'utf8')<=75);
assert.ok(unfold(folded).includes('SUMMARY:'+event.title));
event.title='제목\r\nBEGIN:VEVENT';event.place='홀\rATTENDEE:evil';event.url='javascript:alert(1)';
const injection=unfold(evaluate('makeIcs(event)'));
assert.equal((injection.match(/\r\nBEGIN:VEVENT/g)||[]).length,1);
assert.ok(!injection.includes('\r\nATTENDEE:evil'));
assert.ok(!injection.includes('javascript:'));
evaluate('downloadCalendar(event)');
assert.ok(clicked&&removed&&appended&&revoked);
assert.equal(blob.type,'text/calendar;charset=utf-8');
assert.equal(link.download,'snu-event-123.ics');
assert.equal(link.href,'blob:calendar');
"""
    result = subprocess.run([node, "-e", script, str(page)], stdin=subprocess.DEVNULL, capture_output=True,
                            text=True, encoding="utf-8", timeout=20)
    assert result.returncode == 0, result.stderr
