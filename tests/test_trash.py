"""Exercise trash rendering, browser handlers, persistence and expiry using the page JS."""
import shutil
import subprocess
from pathlib import Path


def run_browser(checks, storage_fails=False):
    node = shutil.which("node")
    assert node, "Node.js is required for trash regression tests"
    setup = r"""
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const page=fs.readFileSync(process.argv[1],'utf8');
const source=page.split('<script>')[1].split('</script>')[0];
const elements={},handlers={},timers=new Map(),stored={};let timerId=0,storageFails=false,copied;
const element=id=>elements[id]||={dataset:{},value:'',setAttribute(key,value){this[key]=value},
 addEventListener(type,fn){handlers[id+':'+type]=fn},showModal(){this.open=true},close(){this.open=false}};
const rows=[
 ['today','2026-11-20','2026-11-20'],['ongoing','2026-11-19','2026-11-22'],
 ['next','2026-11-24','2026-11-24'],['month','2026-11-30','2026-11-30'],
 ['old','2026-10-01','2026-10-20'],['boundary','2026-10-21','2026-10-21']
].map(([id,begin,end])=>({id,title:id,begin,end,type:'공연',time:'',summary:'',url:'https://www.snu.ac.kr/snunow/events'}));
const location={href:'https://example.com/?keep=1',hash:''};
const context=vm.createContext({URL,Intl,Date,location,
 localStorage:{getItem(key){if(storageFails)throw Error('denied');return stored[key]},
 setItem(key,value){if(storageFails)throw Error('quota');stored[key]=value}},
 navigator:{clipboard:{async writeText(value){copied=value}}},
 setTimeout(fn){timers.set(++timerId,fn);return timerId},clearTimeout(id){timers.delete(id)},setInterval(){},
 fetch:async()=>({ok:true,json:async()=>({events:rows,fetched_at:new Date().toISOString()})}),
 window:{addEventListener(type,fn){handlers['window:'+type]=fn}},
 document:{getElementById:element,querySelector(){return element('periods')},querySelectorAll(){return []}}});
const run=code=>vm.runInContext(code,context);
// Full initialization and async fetch, including startup storage access.
const click=(id,target={})=>handlers[id+':click']({target:{closest(){return null},...target}});
const action=(kind,id)=>click('list',{closest(selector){return selector===`[data-${kind}-id]`?{dataset:{[kind+'Id']:id}}:null}});
const listed=id=>elements.list.innerHTML.includes('>'+id+'</a>');
(async()=>{
 run(source.replace(/restoreSettings\(\);\s*window\./, "seoulToday=()=> '2026-11-20';restoreSettings();\nwindow."));
 await new Promise(setImmediate);
"""
    result = subprocess.run(
        [node, "-e", setup.replace("storageFails=false", "storageFails=" + str(storage_fails).lower()) + checks + "\n})().catch(e=>{console.error(e);process.exitCode=1});",
         str(Path(__file__).resolve().parents[1] / "docs/index.html")],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8", timeout=20,
    )
    assert result.returncode == 0, result.stderr


def test_discard_restore_undo_and_bulk_selection():
    run_browser(r"""
assert.ok(listed('today'));
action('discard','today');assert.ok(!listed('today'));
assert.equal(elements['trash-open'].textContent,'휴지통 1');
assert.equal(elements['undo-toast'].hidden,false);
click('trash-undo');assert.ok(listed('today'));assert.equal(run('trashIds().length'),0);
click('list-actions',{id:'select-mode'});
for(const id of ['today','ongoing'])handlers['list:change']({target:{dataset:{selectId:id},checked:true}});
assert.ok(elements['list-actions'].innerHTML.includes('선택한 2개 버리기'));
click('list-actions',{id:'discard-selected'});assert.ok(!listed('today')&&!listed('ongoing'));
assert.equal(timers.size,1); // A new batch replaces the earlier undo timer.
click('trash-open');assert.ok(listed('today')&&listed('ongoing'));
assert.ok(elements.list.innerHTML.includes('data-restore-id="today"'));
action('restore','today');assert.ok(!listed('today'));assert.equal(run('trashIds().length'),1);
click('list-actions',{id:'restore-all'});assert.equal(run('trashIds().length'),0);
click('trash-open');assert.ok(listed('today')&&listed('ongoing'));
// Expiring the notification keeps the discard and disables undo.
action('discard','today');for(const fn of [...timers.values()])fn();
assert.equal(elements['undo-toast'].hidden,true);click('trash-undo');assert.ok(!listed('today'));
""")


def test_every_period_counts_search_and_chronological_trash():
    run_browser(r"""
run("discardIds(['today','ongoing','next','month'])");
for(const period of ['today','week','next','month','all','me']){
 context.period=period;run('state.period=period;render()');
 for(const id of ['today','ongoing','next','month'])assert.ok(!listed(id),period+':'+id);
 assert.ok(elements.chips.innerHTML.includes('<small>'+(period==='all'?2:0)+'</small>'));
}
run("state.query='today';render()");assert.equal(elements.count.textContent,'0개의 행사');
run("state.selected.add('전시')");click('trash-open');
const positions=['ongoing','today','next','month'].map(id=>elements.list.innerHTML.indexOf('>'+id+'</a>'));
assert.ok(positions.every((pos,i)=>pos>=0&&(!i||pos>positions[i-1])));
assert.equal(elements.count.textContent,'4개의 행사');assert.ok(!elements.list.innerHTML.includes('past-events'));
click('list-actions',{id:'trash-empty'});assert.equal(run('trashIds().length'),0);
click('trash-undo');assert.equal(run('trashIds().length'),4);
click('list-actions',{id:'trash-empty'});click('trash-open');
run("state.period='all';state.query='';state.selected.clear();render()");
assert.ok(!listed('today')); // Emptying the trash must not restore discarded cards.
""")


def test_thirty_day_cleanup_including_events_missing_from_feed():
    run_browser(r"""
run("discardIds(['old','boundary','today'])");
assert.equal(run("preferences.dismissed.includes('old')"),false);
assert.equal(run("preferences.dismissed.includes('boundary')"),true);
// Feed retention is shorter than trash retention; remember the end date locally.
run("state.events=[];pruneDismissed('2026-11-21')");
assert.equal(run("preferences.dismissed.includes('boundary')"),false);
assert.equal(run("preferences.dismissed.includes('today')"),true);
run("pruneDismissed('2026-12-21')");assert.equal(run('preferences.dismissed.length'),0);
assert.deepEqual(JSON.parse(stored['snu-events.me.v1']).dismissalEnds,{});
""")


def test_settings_hash_roundtrip_reload_and_legacy_links():
    run_browser(r"""
run("discardIds(['today','ongoing']);state.trash=true;emptyTrash();discardIds(['next'])");
await run('copySettingsLink()');const url=new URL(copied);assert.equal(url.search,'?keep=1');
const original=run('JSON.stringify(cleanSettings(preferences))');
run('preferences={types:[],keywords:[],excluded:[]};restoreSettings()');
assert.equal(run('JSON.stringify(preferences)'),original);
context.location.hash=url.hash;
run('preferences={};importSettingsHash();render()');
assert.equal(run('JSON.stringify(preferences)'),original);
assert.equal(run('trashIds().join()'),'next');assert.ok(!listed('today'));
const saved=JSON.parse(decodeURIComponent(url.hash.slice(4)));
assert.deepEqual(saved.dismissed,['today','ongoing','next']);assert.ok(saved.dismissalEnds.today);
context.location.hash='#me='+encodeURIComponent(JSON.stringify({keywords:['AI']}));
run('importSettingsHash();render()');assert.equal(run('preferences.dismissed.length'),0);
assert.equal(run('preferences.keywords[0]'),'AI');
""")


def test_storage_failures_still_render_and_keep_in_memory_state():
    run_browser(r"""
storageFails=true;run('restoreSettings();render()');assert.ok(listed('today'));
action('discard','today');assert.ok(!listed('today'));
click('trash-undo');assert.ok(listed('today'));
run("discardIds(['next']);state.period='next';render()");assert.ok(!listed('next'));
click('trash-open');assert.ok(listed('next'));action('restore','next');
assert.equal(run('trashIds().length'),0);
// Accessing the localStorage property itself may also throw.
Object.defineProperty(context,'localStorage',{get(){throw Error('blocked')}});
run('restoreSettings();render()');assert.equal(elements.count.textContent,'0개의 행사');
assert.ok(page.includes('구독 캘린더(.ics)는 미리 만든 파일이므로 휴지통에 버린 행사도 포함됩니다.'));
""", storage_fails=True)
