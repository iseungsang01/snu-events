"""Run actual page logic and browser handlers offline, including IME and storage failures."""
import shutil
import subprocess
from pathlib import Path


def run_page_script(script):
    node = shutil.which("node")
    assert node, "Node.js is required for personalization regression tests"
    page = Path(__file__).resolve().parents[1] / "docs/index.html"
    setup = r"""
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const page=fs.readFileSync(process.argv[1],'utf8');
const source=page.split('<script>')[1].split('</script>')[0];
const elements={};
const context=vm.createContext({URL,Intl,Date,document:{
 getElementById:id=>elements[id]||={},querySelectorAll:()=>[]}});
vm.runInContext(source.split("document.querySelector('.periods')")[0],context);
const run=code=>vm.runInContext(code,context);
"""
    result = subprocess.run([node, "-e", setup + script, str(page)],
                            stdin=subprocess.DEVNULL, capture_output=True,
                            text=True, encoding="utf-8", timeout=20)
    assert result.returncode == 0, result.stderr


def test_interest_word_boundaries_and_exclusions():
    run_page_script(r"""
const cases=[
 ['AI','KAIST',false],['AI','domain',false],['AI','AI 강연',true],
 ['AI','(AI)',true],['AI','생성형AI',true],['AI','AI강연',true],
 ['AI','ai',true],['AI','ＡＩ 강연',true],['AI',' AI ',true],
 ['AI','AI2',false],['AI','2AI',false],['AI','xAI',false],['AI','AIx',false],
 ['AI','A I',false],['AI','공연 AI 안내',true],['AI','AI_AI',true],
 ['2026','(2026)',true],['2026','20260',false],['2026','a2026',false],
 ['GPT4','GPT4 강연',true],['GPT4','GPT40',false],
 ['생성형 AI','최신 생성형AI강연',true],['생성형AI','생 성 형 A I 강연',true],
 ['글쓰기 상담','글 쓰 기상담 안내',true]
];
// Run the same matrix for inclusion and exclusion, across every searchable field.
for(const [word,text,expected] of cases){
 for(const field of ['title','summary','search_text','body','description']){
  context.row={type:'특강·세미나',[field]:text};context.word=word;
  run('preferences={types:[],keywords:[word],excluded:[]}');
  assert.equal(run('matchesInterests(row)'),expected,`include ${word}: ${field}=${text}`);
  run('preferences={types:[],keywords:[],excluded:[word]}');
  assert.equal(run('matchesInterests(row)'),!expected,`exclude ${word}: ${field}=${text}`);
 }
}
// Joining fields must preserve boundaries rather than creating English words.
context.row={title:'AI',summary:'lecture',type:'특강·세미나'};
run("preferences={types:[],keywords:['AI'],excluded:[]}");
assert.equal(run('matchesInterests(row)'),true);
context.row={title:'A',summary:'I',type:'특강·세미나'};
assert.equal(run('matchesInterests(row)'),false);
""")


def test_my_interests_groups_ongoing_before_today_and_future():
    run_page_script(r"""
run(`seoulToday=()=> '2026-11-20';state.loaded=true;state.period='me';
 state.events=[
 ['later','2026-11-23','2026-11-25'],['tomorrow','2026-11-21','2026-11-21'],
 ['today','2026-11-20','2026-11-20'],['starts-today','2026-11-20','2026-12-01'],
 ['ongoing','2026-09-03','2026-12-01'],['ends-today','2026-11-19','2026-11-20'],
 ['past','2026-09-01','2026-11-19']
 ].map(([id,begin,end])=>({id,title:id,begin,end,type:'공연',time:'',
 url:'https://www.snu.ac.kr/snunow/events'}));render()`);
const html=elements.list.innerHTML;
const groups=html.split('<section class="group">').slice(1);
const title=group=>group.split('</h3>')[0];
assert.equal(groups.length,4);
assert.ok(title(groups[0]).includes('진행 중<span>2개</span>'));
assert.ok(!title(groups[0]).includes('9월'));
for(const id of ['ongoing','ends-today'])assert.ok(groups[0].includes(`>${id}</a>`));
for(const id of ['today','starts-today'])assert.ok(groups[1].includes(`>${id}</a>`));
for(const [i,date] of [[1,'2026-11-20'],[2,'2026-11-21'],[3,'2026-11-23']]){
 context.date=date;assert.ok(title(groups[i]).includes(run('displayDate(date)')));
}
assert.ok(title(groups[1]).includes(' · 오늘'));
assert.ok(groups[2].includes('>tomorrow</a>'));assert.ok(groups[3].includes('>later</a>'));
assert.ok(!html.includes('>past</a>'));assert.equal(elements.count.textContent,'6개의 행사');
for(const id of ['ongoing','ends-today','today','starts-today','tomorrow','later']){
 assert.equal(html.split(`>${id}</a>`).length-1,1);
}
// Filtering away ongoing events must also remove their heading.
run("state.query='later';render()");
assert.ok(!elements.list.innerHTML.includes('진행 중'));
assert.ok(elements.list.innerHTML.includes('>later</a>'));
run("state.query='ongoing';render()");
assert.equal(elements.list.innerHTML.split('<section class="group">').length-1,1);
assert.ok(elements.list.innerHTML.includes('진행 중'));
""")


def test_word_entry_buttons_keep_single_line():
    run_page_script(r"""
// Both add buttons share the flex rule; inputs may shrink, buttons may not.
const style=page.split('<style>')[1].split('</style>')[0];
const rule=style.match(/\.word-entry button\{([^}]+)\}/)[1];
assert.match(rule,/(?:^|;)white-space:nowrap(?:;|$)/);
assert.match(rule,/(?:^|;)flex-shrink:0(?:;|$)/);
assert.match(rule,/(?:^|;)min-width:4em(?:;|$)/);
assert.match(style,/\.word-entry input\{[^}]*min-width:0/);
for(const key of ['keywords','excluded']){
 assert.ok(page.includes(`<button type="button" data-add-word="${key}">추가</button>`));
}
""")


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
