"""Run actual page logic and browser handlers offline, including IME and storage failures."""
import shutil
import subprocess
from pathlib import Path


def test_personalization_browser_flow():
    node = shutil.which("node")
    assert node
    page = Path(__file__).resolve().parents[1] / "docs/index.html"
    script = r"""
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const page=fs.readFileSync(process.argv[1],'utf8');
const source=page.split('<script>')[1].split('</script>')[0];
const elements={},handlers={},stored={};let copied,storageFails=false;
const element=id=>elements[id]||={dataset:{},value:'',addEventListener(type,fn){handlers[id+':'+type]=fn},
 showModal(){this.open=true},close(){this.open=false},focus(){},select(){}};
const context=vm.createContext({URL,Intl,Date,location:{href:'https://example.org/events/?q=1#old',hash:''},
 localStorage:{getItem(key){if(storageFails)throw Error('blocked');return stored[key]},setItem(key,value){if(storageFails)throw Error('quota');stored[key]=value}},
 navigator:{clipboard:{async writeText(value){copied=value}}},
 document:{getElementById:element,querySelector(){return {addEventListener(){}}},querySelectorAll(){return []}}});
vm.runInContext(source.split("$('list').addEventListener")[0],context);
const run=code=>vm.runInContext(code,context);
run(`preferences={types:['performance','lecture'],keywords:['글쓰기 상담','음악 & 😀 #/%'],excluded:['마감 임박']}`);
const original=run('JSON.stringify(cleanSettings(preferences))');
const hash=run('encodeSettings(preferences)');context.hash=hash;
assert.ok(hash.startsWith('#me=%7B'));assert.ok(!hash.includes('글쓰기'));
assert.equal(run('JSON.stringify(decodeSettings(hash))'),original);
for(const bad of ['','#else=abc','#me=%XX','#me=null','#me=[]','#me={']){
 context.bad=bad;assert.equal(run('decodeSettings(bad)'),null);
}
run('saveSettings();preferences={};restoreSettings()');assert.equal(run('JSON.stringify(preferences)'),original);
stored['snu-events.me.v1']='broken json';run('restoreSettings()');assert.equal(run('JSON.stringify(preferences)'),original);
storageFails=true;run('saveSettings();restoreSettings()');
context.location.hash=hash;
run('preferences={};restoreSettings()');assert.equal(run('JSON.stringify(preferences)'),original);
assert.equal(run('state.period'),'me'); // Hash import wins even when storage is unavailable.
storageFails=false;
context.location.hash='';
context.row={title:'글쓰기상담',summary:'자유롭게 참여',type:'특강·세미나'};
assert.equal(run('matchesInterests(row)'),true);
context.row.title='다른 제목';context.row.summary='글 쓰 기\t상 담 안내';
assert.equal(run('matchesInterests(row)'),true);
context.row.summary+=' 마 감임박';assert.equal(run('matchesInterests(row)'),false);
context.row.summary='음악 & 😀 #/%';assert.equal(run('matchesInterests(row)'),true);
context.row.type='전시';assert.equal(run('matchesInterests(row)'),false);
context.row.type='공연';context.row.summary='관련 없는 행사';assert.equal(run('matchesInterests(row)'),false);
run('preferences={types:[],keywords:[],excluded:[]}');assert.equal(run('matchesInterests(row)'),true);
// Exercise wired IME listeners, including Safari/legacy 229 and composition tracking.
const input=element('keywords-input');input.value='글쓰기 상담';
const enter=extra=>({key:'Enter',target:input,preventDefault(){this.prevented=true},...extra});
handlers['keywords-input:compositionstart']();
for(const event of [enter({isComposing:true}),enter({keyCode:229}),enter({})]){
 handlers['keywords-input:keydown'](event);assert.ok(!event.prevented);
}
assert.equal(run('preferences.keywords.length'),0);assert.equal(input.value,'글쓰기 상담');
handlers['keywords-input:compositionend']();
const event=enter({});handlers['keywords-input:keydown'](event);assert.ok(event.prevented);
assert.equal(run('preferences.keywords[0]'),'글쓰기 상담');assert.equal(input.value,'');
input.value='글쓰기 상담';handlers['keywords-input:keydown'](enter({}));assert.equal(run('preferences.keywords.length'),1);
// Upcoming and ongoing events stay chronological, including multi-day cards.
run(`seoulToday=()=> '2026-11-20';state.loaded=true;state.period='me';state.selected.add('전시');
 state.events=[['later','2026-11-23','2026-11-23'],['middle','2026-11-21','2026-11-22'],
 ['today','2026-11-20','2026-11-20'],['ongoing','2026-11-19','2026-11-21'],['past','2026-11-18','2026-11-19']]
 .map(([id,begin,end])=>({id,title:id+' 글쓰기상담',summary:'',type:'공연',begin,end,time:'',url:'https://www.snu.ac.kr/snunow/events'}));render()`);
const html=elements.list.innerHTML;
assert.ok(!html.includes('>past 글쓰기상담</a>'));
const titles=['ongoing','today','middle','later'].map(id=>html.indexOf('>'+id+' 글쓰기상담</a>'));
assert.ok(titles.every((pos,i)=>pos>=0&&(!i||pos>titles[i-1])));
assert.equal((html.match(/class="calendar-add"/g)||[]).length,4);
handlers['chips:click']({target:{closest(){return {dataset:{type:'공연'}}}}});
assert.equal(run('preferences.types.join()'),'performance');
assert.ok(elements.chips.innerHTML.includes('data-type="공연" aria-pressed="true"'));
assert.equal(JSON.parse(stored['snu-events.me.v1']).types[0],'performance');
// Every nonempty checkbox combination resolves to the generator's canonical name.
for(let mask=1;mask<64;mask++){
 context.mask=mask;
 const keys=run('CALENDAR_KEYS.filter((_,i)=>mask&(1<<i))');context.keys=keys;
 const expected=mask===63?'all':[...keys].sort().join('-');
 assert.equal(run('combinationKey(keys)'),expected);
}
assert.equal(run('combinationKey([])'),'');
run("preferences.types=['performance','lecture'];renderSubscriptions()");
assert.ok(elements['subscribe-mix'].innerHTML.includes('/mix/lecture-performance.ics'));
assert.ok(elements['subscribe-mix'].innerHTML.includes('https://calendar.google.com/calendar/r?cid='+encodeURIComponent('webcal://iseungsang01.github.io/snu-events/calendar/mix/lecture-performance.ics')));
handlers['subscribe-types:change']({target:{dataset:{subscribeType:'lecture'},checked:false}});
assert.ok(elements['subscribe-mix'].innerHTML.includes('/mix/performance.ics'));
handlers['subscribe-types:change']({target:{dataset:{subscribeType:'performance'},checked:false}});
assert.ok(!elements['subscribe-mix'].innerHTML.includes('href='));
assert.ok(page.includes('키워드 조건은 페이지에서만 적용되고, 구독 캘린더는 고른 종류 기준'));
(async()=>{
 context.button={dataset:{copyCalendar:'mix/lecture-performance'}};
 await run('copySubscription(button)');assert.equal(copied,'webcal://iseungsang01.github.io/snu-events/calendar/mix/lecture-performance.ics');
 await run('copySettingsLink()');const link=new URL(copied);assert.equal(link.search,'?q=1');
 context.hash=link.hash;assert.equal(run('JSON.stringify(decodeSettings(hash))'),run('JSON.stringify(cleanSettings(preferences))'));
})().catch(error=>{console.error(error);process.exitCode=1});
"""
    result = subprocess.run([node, "-e", script, str(page)], stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, encoding="utf-8", timeout=20)
    assert result.returncode == 0, result.stderr
