"""Exercise the page's actual rendering code offline with Node's VM."""
import shutil
import os
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


@pytest.mark.parametrize("timezone", ["UTC", "America/Los_Angeles", "Asia/Seoul"])
def test_google_links_and_subscriptions(timezone):
    node = shutil.which("node")
    assert node
    page = Path(__file__).resolve().parents[1] / "docs/index.html"
    script = r"""
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const page=fs.readFileSync(process.argv[1],'utf8');
const source=page.split('<script>')[1].split('</script>')[0];
const elements={},handlers={};let copied;
const element=id=>elements[id]||=( {addEventListener(type,fn){handlers[id+':'+type]=fn},
  showModal(){this.open=true},close(){this.open=false}} );
const context=vm.createContext({URL,Intl,Date,navigator:{clipboard:{async writeText(value){copied=value}}},
  document:{getElementById:element,querySelector(){return {addEventListener(){}}}}});
vm.runInContext(source.split("$('list').addEventListener")[0],context);
const evaluate=code=>vm.runInContext(code,context);
context.event={id:'123',title:'공연 & 특별',begin:'2026-11-20',end:'2026-11-20',
  time:'14:00~16:20',place:'예술관, 콘서트홀',summary:'소개\n한 줄',url:'https://www.snu.ac.kr/snunow/events?bbsidx=123'};
const params=()=>new URL(evaluate('googleCalendarUrl(event)')).searchParams;
let p=params();
assert.equal(p.get('action'),'TEMPLATE');assert.equal(p.get('text'),context.event.title);
assert.equal(p.get('dates'),'20261120T140000/20261120T162000');assert.equal(p.get('ctz'),'Asia/Seoul');
assert.equal(p.get('location'),context.event.place);assert.equal(p.get('details'),'소개 한 줄\n원문: '+context.event.url);
for(const [time,end,expected,tz] of [
  ['14:00','2026-11-20','20261120T140000/20261120T150000','Asia/Seoul'],
  ['23:30','2026-11-20','20261120T233000/20261121T003000','Asia/Seoul'],
  ['23:30~01:00','2026-11-20','20261120T233000/20261121T010000','Asia/Seoul'],
  ['','2026-11-20','20261120/20261121',null],
  ['14:00~16:20','2026-11-22','20261120/20261123',null],
  ['','2026-11-22','20261120/20261123',null],
  ['미정','2026-11-20','20261120/20261121',null]
]){context.event.time=time;context.event.end=end;p=params();assert.equal(p.get('dates'),expected);assert.equal(p.get('ctz'),tz)}
context.event.begin='2026-12-31';context.event.end='2026-12-31';context.event.time='';
assert.equal(params().get('dates'),'20261231/20270101');
const html=evaluate('card(event,"2026-11-20")');
assert.match(html,/<a class="calendar-add"[^>]*calendar.google.com[^>]*target="_blank"[^>]*rel="noopener noreferrer"/);
assert.ok(html.includes('Google 캘린더에 추가'));assert.ok(html.includes('다른 캘린더(.ics)'));
evaluate("state.selected.add('전시');state.selected.add('특강·세미나')");
handlers['subscribe-open:click']();assert.equal(elements['subscribe-dialog'].open,true);
const feeds=elements['subscribe-feeds'].innerHTML;
assert.ok(feeds.indexOf('<h3>전시</h3>')<feeds.indexOf('<h3>전체</h3>'));
assert.ok(feeds.indexOf('<h3>특강·세미나</h3>')<feeds.indexOf('<h3>전체</h3>'));
for(const key of ['all','performance','exhibition','contest','lecture','recruit','other']){
  const address=`webcal://iseungsang01.github.io/snu-events/calendar/${key}.ics`;
  assert.ok(feeds.includes(`href="${address}"`));
  assert.ok(feeds.includes('https://calendar.google.com/calendar/r?cid='+encodeURIComponent(address)));
  assert.ok(feeds.includes(`data-copy-calendar="${key}"`));
}
context.button={dataset:{copyCalendar:'exhibition'}};
(async()=>{
 await evaluate('copySubscription(button)');
 assert.equal(copied,'webcal://iseungsang01.github.io/snu-events/calendar/exhibition.ics');
 assert.equal(elements['copy-status'].textContent,'캘린더 주소를 복사했어요.');
 handlers['subscribe-close:click']();assert.equal(elements['subscribe-dialog'].open,false);
 assert.ok(page.includes('구독하면 매일 아침 갱신된 행사가 캘린더에 자동으로 들어옵니다(캘린더 앱마다 반영 주기는 다를 수 있음).'));
})().catch(error=>{console.error(error);process.exitCode=1});
"""
    result = subprocess.run([node, "-e", script, str(page)], stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, encoding="utf-8", timeout=20,
                            env={**os.environ, "TZ": timezone})
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
assert.ok(single.includes('DTEND:20261119T163000Z'));
event.time='14:00~16:00';event.end='2026-11-22';
assert.ok(unfold(evaluate('makeIcs(event)')).includes('DTEND;VALUE=DATE:20261123'));
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
