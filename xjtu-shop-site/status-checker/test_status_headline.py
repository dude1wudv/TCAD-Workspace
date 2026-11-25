import json
from pathlib import Path
import shutil
import subprocess
import unittest


# Minimal DOM model for the browser APIs exercised by status.js.
NODE_DOM = r"""

const decode = (value) => value.replaceAll('&lt;','<').replaceAll('&gt;','>').replaceAll('&quot;','"').replaceAll('&#039;',"'").replaceAll('&amp;','&');
const escape = (value) => String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
const voidTags = new Set(['area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr']);
let document;
class MockNode {
  constructor(name, value = null) {
    this.nodeType = name === '#text' ? 3 : name === '#fragment' ? 11 : 1;
    this.nodeName = this.nodeType === 1 ? name.toUpperCase() : name;
    this.tagName = this.nodeType === 1 ? this.nodeName : undefined;
    this.nodeValue = value;
    this.childNodes = [];
    this.parentNode = null;
    this.attributeMap = new Map();
    this.listeners = new Map();
    this.updateComplete = Promise.resolve();
    this.scrollTop = 0;
    this.offsetWidth = 100;
  }
  get attributes() { return [...this.attributeMap].map(([name,value])=>({name,value})); }
  get id() { return this.getAttribute('id') || ''; }
  get dataset() { return Object.fromEntries(this.attributes.filter(a=>a.name.startsWith('data-')).map(a=>[a.name.slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase()),a.value])); }
  get classList() {
    return {
      contains: (name) => (this.getAttribute('class') || '').split(/\s+/).includes(name),
      toggle: (name, force) => {
        const names = new Set((this.getAttribute('class') || '').split(/\s+/).filter(Boolean));
        const include = force ?? !names.has(name);
        if (include) names.add(name); else names.delete(name);
        this.setAttribute('class',[...names].join(' '));
        return include;
      },
    };
  }
  get open() { return this.hasAttribute('open'); }
  set open(value) { this.toggleAttribute('open',value); }
  get disabled() { return this.hasAttribute('disabled'); }
  set disabled(value) { this.toggleAttribute('disabled',value); }
  get firstChild() { return this.childNodes[0] || null; }
  get nextSibling() { return this.parentNode?.childNodes[this.parentNode.childNodes.indexOf(this)+1] || null; }
  get nextElementSibling() { return this.parentNode?.childNodes.slice(this.parentNode.childNodes.indexOf(this)+1).find(node=>node.nodeType===1) || null; }
  get isConnected() { return this === document.body || Boolean(this.parentNode?.isConnected); }
  get textContent() { return this.nodeType === 3 ? this.nodeValue : this.childNodes.map(n=>n.textContent).join(''); }
  set textContent(value) {
    if (this.nodeType === 3) { this.nodeValue = String(value); return; }
    this.childNodes = [];
    if (value !== '') {
      const text = new MockNode('#text',String(value));
      text.parentNode = this;
      this.childNodes.push(text);
    }
  }
  get innerHTML() { return this.childNodes.map(n=>n.outerHTML).join(''); }
  set innerHTML(value) {
    for (const node of [...this.childNodes]) this.removeChild(node);
    parse(this, value);
  }
  get outerHTML() {
    if (this.nodeType === 3) return escape(this.nodeValue);
    const tag = this.nodeName.toLowerCase();
    const attrs = this.attributes.map(a=>' '+a.name+'="'+escape(a.value)+'"').join('');
    return '<'+tag+attrs+'>'+this.innerHTML+(voidTags.has(tag)?'':'</'+tag+'>');
  }
  hasAttribute(name) { return this.attributeMap.has(name); }
  getAttribute(name) { return this.attributeMap.get(name) ?? null; }
  setAttribute(name,value) { this.attributeMap.set(name,String(value)); }
  removeAttribute(name) { this.attributeMap.delete(name); }
  toggleAttribute(name,force) {
    const include = force ?? !this.hasAttribute(name);
    if (include) this.setAttribute(name,''); else this.removeAttribute(name);
    return include;
  }
  contains(node) { return node === this || this.childNodes.some(child=>child.contains(node)); }
  insertBefore(node,before) {
    if (node === before) return node;
    if (node.parentNode) node.parentNode.removeChild(node);
    const index = before ? this.childNodes.indexOf(before) : this.childNodes.length;
    assert.ok(index >= 0,'insertBefore target must belong to the parent');
    this.childNodes.splice(index,0,node);
    node.parentNode = this;
    return node;
  }
  removeChild(node) {
    const index = this.childNodes.indexOf(node);
    assert.ok(index >= 0,'removeChild target must belong to the parent');
    if (node.contains(document.activeElement)) document.activeElement = document.body;
    this.childNodes.splice(index,1);
    node.parentNode = null;
    return node;
  }
  remove() { if (this.parentNode) this.parentNode.removeChild(this); }
  cloneNode(deep) {
    const clone = new MockNode(this.nodeName.toLowerCase(),this.nodeValue);
    for (const a of this.attributes) clone.setAttribute(a.name,a.value);
    if (deep) for (const child of this.childNodes) clone.insertBefore(child.cloneNode(true),null);
    return clone;
  }
  matches(selector) {
    return selector.split(',').some(part=>{
      part = part.trim();
      const tag = part.match(/^[a-z][\w-]*/i)?.[0];
      if (tag && this.nodeName.toLowerCase() !== tag.toLowerCase()) return false;
      const id = part.match(/#([\w-]+)/)?.[1];
      if (id && this.id !== id) return false;
      for (const match of part.matchAll(/\.([\w-]+)/g)) if (!this.classList.contains(match[1])) return false;
      for (const match of part.matchAll(/\[([\w-]+)(?:="([^"]*)")?\]/g)) {
        if (!this.hasAttribute(match[1]) || (match[2] !== undefined && this.getAttribute(match[1]) !== match[2])) return false;
      }
      return this.nodeType === 1;
    });
  }
  querySelectorAll(selector) {
    const matches = [];
    const visit = (node) => {
      for (const child of node.childNodes) {
        if (child.matches(selector)) matches.push(child);
        visit(child);
      }
    };
    visit(this);
    return matches;
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  closest(selector) { return this.matches(selector) ? this : this.parentNode?.closest(selector) || null; }
  focus() { document.activeElement = this; }
  scrollIntoView() {}
  addEventListener(type,callback) {
    if (!this.listeners.has(type)) this.listeners.set(type,[]);
    this.listeners.get(type).push(callback);
  }
  dispatchEvent(event) {
    event.target ||= this;
    event.currentTarget = this;
    for (const callback of this.listeners.get(event.type) || []) callback(event);
    if (event.bubbles && this.parentNode) this.parentNode.dispatchEvent(event);
    return true;
  }
  click() { if (!this.disabled) this.dispatchEvent({type:'click',bubbles:true}); }
  async show() {
    this.dispatchEvent({type:'open'});
    this.open = true;
    this.querySelector('[autofocus]')?.focus();
    this.dispatchEvent({type:'opened'});
  }
  async close() {
    this.dispatchEvent({type:'close'});
    this.open = false;
    this.dispatchEvent({type:'closed'});
  }
  cancel() { this.dispatchEvent({type:'cancel'}); return this.close(); }
}
function parse(parent, html) {
  const stack = [parent];
  for (const token of html.match(/<!--[\s\S]*?-->|<\/?[^>]+>|[^<]+/g) || []) {
    if (token.startsWith('<!--')) continue;
    if (token.startsWith('</')) { stack.pop(); continue; }
    if (token.startsWith('<')) {
      const name = token.match(/^<([\w-]+)/)?.[1];
      assert.ok(name,'valid element');
      const node = new MockNode(name);
      const rest = token.slice(name.length+1).replace(/\/?>$/,'');
      for (const match of rest.matchAll(/([^\s=]+)(?:\s*=\s*"([^"]*)")?/g)) node.setAttribute(match[1],decode(match[2] || ''));
      stack[stack.length-1].insertBefore(node,null);
      if (!voidTags.has(name) && !token.endsWith('/>')) stack.push(node);
    } else stack[stack.length-1].insertBefore(new MockNode('#text',decode(token)),null);
  }
}
class MockTemplate extends MockNode {
  constructor() { super('template'); this.content = new MockNode('#fragment'); }
  set innerHTML(value) { this.content.innerHTML = value; }
}
document = {
  documentElement:{dataset:{}}, body: new MockNode('body'), hidden:false, cookie:'', addEventListener() {},
  createElement:(name)=>name === 'template' ? new MockTemplate() : new MockNode(name),
  querySelector:(selector)=>document.body.querySelector(selector),
  querySelectorAll:(selector)=>document.body.querySelectorAll(selector),
  getElementById:(id)=>document.body.querySelectorAll('[id]').find(n=>n.id===id) || null,
};
document.activeElement = document.body;
const app = new MockNode('div');
app.setAttribute('id','app');
document.body.insertBefore(app,null);
const media = new Map();
const matchMedia = (query) => {
  if (!media.has(query)) media.set(query,{matches:false,listeners:[],addEventListener(type,callback){this.listeners.push(callback);}});
  return media.get(query);
};
let timerId = 0;
const timers = new Map();
const savedValues = new Map([['xjtu-slot-replay-event','launch-1']]);
const context = vm.createContext({
  assert,fs,SOURCE_PATH,app,
  document,window:{matchMedia},matchMedia,location:{hostname:'status.xjtu.shop'},
  systemTheme:{matches:false,addEventListener(){}},statusTheme:'light',applyStatusTheme:()=>{},
  AbortSignal:{timeout:()=>undefined},
  localStorage:{getItem:(k)=>savedValues.get(k),setItem:(k,v)=>savedValues.set(k,v)},
  setInterval:()=>0,setTimeout:(callback)=>{timers.set(++timerId,callback);return timerId;},clearTimeout:(id)=>timers.delete(id),
  fetch:()=>new Promise(()=>{}),
});

"""


@unittest.skipUnless(shutil.which("node"), "Node.js is required for status headline rendering checks")
class StatusHeadlineTests(unittest.TestCase):
    def render_headline(self, research, language="zh", checks=""):
        source = Path(__file__).resolve().parents[1] / "src/status.js"
        research_source = source.with_name("research-dashboard.js")
        script = (
            "import assert from 'node:assert/strict';\n"
            "import fs from 'node:fs';\nimport vm from 'node:vm';\n"
            "const SOURCE_PATH=" + json.dumps(str(source)) + ";\n"
            "const RESEARCH_PATH=" + json.dumps(str(research_source)) + ";\n"
            "const TELEMETRY_PATH=" + json.dumps(str(source.with_name("components") / "telemetry-charts.js")) + ";\n"
            "const I18N_PATH=" + json.dumps(str(source.with_name("shared") / "i18n.js")) + ";\n"
            "const RESEARCH=" + json.dumps(research) + ";\n"
            "const LANGUAGE=" + json.dumps(language) + ";\n"
            "const CHECKS=" + json.dumps(checks) + ";\n" + NODE_DOM + r"""
const source = fs.readFileSync(SOURCE_PATH,'utf8');
const test = `
state.lang = ${JSON.stringify(LANGUAGE)};
state.refreshing = false;
const payload = {
  overall:'maintenance', services:[], generated_at:new Date().toISOString(),
  simulation:{controller_mode:'maintenance',updated_at:new Date().toISOString()},
  research:${JSON.stringify(RESEARCH)}
};
state.live = payload;
state.full = payload;
state.liveMode = 'online';
function schedulerFixture() {
  const now = new Date().toISOString();
  return {
    id:'task-1',label:'1×10 性能测试',kind:'benchmark',state:'running',
    observed_at:now,observation_stale:false,capacity:1,requested_threads:10,
    slot_count:10,active_slots:10,cpu_set:Array.from({length:10},(_,i)=>i),
    started_at:now,elapsed_seconds:12,
    slots:Array.from({length:11},(_,i)=>({
      index:i,cpu:i,label:'CPU '+i,state:i<10?'running':'idle',
      task_id:i<10?'task-1':null,cluster:i<10?'task-1':'idle-10',threads:i<10?1:0,
    })),
    tasks:[{id:'task-1',label:'D0 · O2 · b0',kind:'benchmark',state:'running',
      requested_threads:10,cpu_set:Array.from({length:10},(_,i)=>i),
      started_at:now,elapsed_seconds:12,parameters:{numerical_threads:10,research_samples:0,
        temperature_K:300,theta_deg:0,phi_deg:0,source_window_width_coord:0.174,
        source_window_height_coord:0.06,particle_injection:'not_injected',device_geometry:'mesh_dimensions_unavailable'},
      progress:{simulation_time_ns:10.082,goal_time_ns:35,updated_at:now}}],
    replay:{event_id:'launch-1',available:true,started_at:now,duration_ms:1600},
    virtual_machine:{observed_at:now,cpu:{cores:11,usage_percent:90,load_1m:10},
      memory:{total_bytes:28*1024**3,available_bytes:25*1024**3,used_bytes:3*1024**3,used_percent:10.7}},
    controller:{mode:'benchmark',state:'maintenance',dispatch_paused:true},
  };
}
function useScheduler(scheduler = schedulerFixture()) {
  state.live.services = [{
    id:'tcad-controller',state:'maintenance',mode:'benchmark',
    detail:'1×10 性能测试运行中，自动派发暂停',checked_at:new Date().toISOString(),
  }];
  state.live.simulation = {
    scheduler,updated_at:'2026-01-01T00:00:00Z',observation_stale:true,running_groups:10,
    current_runs:[{public_id:'OLD-SNAPSHOT',state:'running',requested_threads:2,elapsed_seconds:123}],
  };
  render();
  return scheduler;
}
render();
` + CHECKS;
const dependencies = new Map();
const researchModule = new vm.SourceTextModule(fs.readFileSync(RESEARCH_PATH,'utf8'),{context});
await researchModule.link(()=>{throw new Error('Unexpected research dependency');});
const telemetryModule = new vm.SourceTextModule(fs.readFileSync(TELEMETRY_PATH,'utf8'),{context});
await telemetryModule.link(()=>{throw new Error('Unexpected telemetry dependency');});
const i18nModule = new vm.SourceTextModule(fs.readFileSync(I18N_PATH,'utf8'),{context});
await i18nModule.link(()=>{throw new Error('Unexpected i18n dependency');});
const module = new vm.SourceTextModule(source+'\n'+test,{context});
await module.link((specifier)=>{
  if (specifier === './research-dashboard.js') return researchModule;
  if (specifier === './components/telemetry-charts.js') return telemetryModule;
  if (specifier === './shared/i18n.js') return i18nModule;
  if (!dependencies.has(specifier)) dependencies.set(specifier,new vm.SyntheticModule([],function(){},{context}));
  return dependencies.get(specifier);
});
await module.evaluate();
const card = [...app.innerHTML.matchAll(/<article class="panel kpi">([\s\S]*?)<\/article>/g)]
  .map((match) => match[1]).find((value) => value.includes('正式进度') || value.includes('Formal plan'));
assert.ok(card,'acceptance headline card was rendered');
process.stdout.write(JSON.stringify({card,html:app.innerHTML}));
""")
        result = subprocess.run(["node", "--experimental-vm-modules", "--input-type=module"],
                                input=script, encoding="utf-8", capture_output=True, timeout=20, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_planner_warning_tracks_explicit_offline_flag_and_freshness(self):
        self.render_headline({}, language="en", checks=r"""
const overview = document.getElementById('overview');
const warning = 'AI repair planner offline';
assert.ok(!overview.textContent.includes(warning));
payload.simulation.planner = {status:'offline', offline:false};
render();
assert.ok(!overview.textContent.includes(warning));
payload.simulation.planner.offline = true;
render();
assert.ok(overview.textContent.includes(warning));
payload.generated_at = new Date(Date.now()-181000).toISOString();
tick();
assert.ok(!overview.textContent.includes(warning));
""")

    def test_scheduler_uses_vm_cores_and_counts_tasks_with_maintenance_reason(self):
        self.render_headline({}, checks=r"""
const scheduler = useScheduler();
const source = schedulerFor(state.live.simulation);
assert.equal(source.count,11);
assert.equal(source.tasks.filter(task=>task.state==='running').length,1);
assert.equal(source.active_slots,10);
const schedule = document.getElementById('schedule');
const cells = schedule.querySelectorAll('.cpu-cell');
assert.equal(cells.length,11);
assert.equal(schedule.querySelectorAll('.cpu-cell.good').length,10);
assert.ok(schedule.querySelector('[data-key="cpu-10"]').classList.contains('neutral'));
assert.ok(document.getElementById('tasks').textContent.includes('D0 · O2 · b0'));
assert.ok(document.getElementById('tasks').textContent.includes('10.082 / 35 ns'));
assert.ok(document.getElementById('services').textContent.includes('维护暂停'));
assert.ok(schedule.textContent.includes('后台余量'));
assert.ok(!document.getElementById('runs').textContent.includes('OLD-SNAPSHOT'));
assert.ok(app.innerHTML.indexOf('id="schedule"') < app.innerHTML.indexOf('id="research"'));
""")

    def test_root_event_delegation_keeps_task_nodes_on_refresh(self):
        self.render_headline({}, checks=r"""
const scheduler = useScheduler();
const task = document.querySelector('[data-task="task-1"]');
const slot = document.querySelector('[data-slot-task="task-1"]');
assert.ok(slot);
slot.click();
assert.equal(state.selectedTask,'task-1');
assert.ok(document.querySelector('[data-task="task-1"]').classList.contains('selected'));
assert.equal(app.listeners.get('click').length,1);
scheduler.tasks[0].elapsed_seconds = 24;
render();
assert.equal(document.querySelector('[data-task="task-1"]'),task);
assert.equal(document.querySelector('[data-slot-task="task-1"]').getAttribute('aria-pressed'),'true');
slot.click();
assert.equal(state.selectedTask,null);
slot.click();
assert.equal(state.selectedTask,'task-1');
document.getElementById('overview').click();
assert.equal(state.selectedTask,null);
""")

    def test_trend_tooltips_use_the_new_root_event_delegate(self):
        self.render_headline({}, checks=r"""
state.live.history = {
  system_fields:['ts','server_cpu_percent','vm_cpu_percent','vm_load_1m','server_available_memory_gib','vm_available_memory_gib','active_solvers','active_cores'],
  system_recent:[[1000,42,35,1.2,20,18,1,2],[1060,48,40,1.4,19,17,1,2]],
  system_5m:[[1000,42,35,1.2,20,18,1,2],[1060,48,40,1.4,19,17,1,2]],
};
render();
const svg = document.querySelector('.trend-svg');
assert.ok(svg);
svg.dispatchEvent({type:'keydown',key:'Home',bubbles:true,preventDefault(){this.prevented=true;}});
assert.ok(svg.nextElementSibling.textContent.includes('服务器'));
assert.ok(svg.nextElementSibling.textContent.includes('42%'));
""")

    def test_responsive_scheduler_grid_uses_new_dashboard_contract(self):
        self.render_headline({}, checks=r"""
useScheduler();
const schedule = document.getElementById('schedule');
const cells = schedule.querySelectorAll('.cpu-cell');
assert.equal(cells.length,11);
assert.equal(schedule.querySelectorAll('.cpu-cluster').length,1);
assert.equal(cells[0].getAttribute('data-key'),'cpu-0');
assert.equal(cells[10].getAttribute('data-key'),'cpu-10');
const css = fs.readFileSync(SOURCE_PATH.replace(/status\.js$/,'status-dashboard.css'),'utf8');
assert.ok(css.includes('.compute-cores'));
assert.ok(css.includes('.cpu-cluster'));
assert.ok(css.includes('@media (min-width: 600px)'));
""")

    def test_missing_and_stale_observations_are_gray_and_collecting_is_pending(self):
        self.render_headline({}, checks=r"""
state.live.simulation = {running_groups:10,requested_threads:10};
render();
assert.equal(document.getElementById('schedule').querySelectorAll('.cpu-cell').length,0);
assert.equal(schedulerFor(state.live.simulation).tasks.length,0);
const scheduler = useScheduler();
scheduler.observed_at = new Date(Date.now()-181000).toISOString();
scheduler.observation_stale = false;
render();
assert.equal(document.getElementById('schedule').querySelectorAll('.cpu-cell.neutral').length,11);
assert.equal(schedulerFor(state.live.simulation).stale,true);
scheduler.observed_at = new Date().toISOString();
scheduler.state = 'collecting';
scheduler.tasks[0].state = 'collecting';
scheduler.slots.forEach(slot=>slot.state='idle');
render();
assert.ok(document.getElementById('tasks').textContent.includes('待收集'));
assert.ok(!document.getElementById('tasks').textContent.includes('已完成'));
""")

    def test_scheduler_priority_legacy_compatibility_and_escaped_public_fields(self):
        self.render_headline({}, checks=r"""
const scheduler = useScheduler();
state.live.simulation.benchmark = {...scheduler,label:'OBSOLETE',tasks:[]};
scheduler.label = '"><img id="injected" src=x>';
scheduler.tasks[0].label = '<script id="injected-task">bad()</script>';
scheduler.tasks[0].parameters = {custom:'<svg id="injected-parameter">bad</svg>'};
scheduler.slots[0].cluster = '"><img id="injected-slot">';
render();
assert.equal(document.getElementById('injected'),null);
assert.equal(document.getElementById('injected-task'),null);
assert.equal(document.getElementById('injected-parameter'),null);
assert.ok(app.innerHTML.includes('&lt;script'));
assert.ok(!app.innerHTML.includes('OBSOLETE'));
delete state.live.simulation.scheduler;
state.live.simulation.benchmark.tasks = undefined;
render();
assert.equal(schedulerFor(state.live.simulation).tasks.length,1);
assert.equal(document.getElementById('schedule').querySelectorAll('.cpu-cell').length,11);
""")

    def test_response_supply_shows_case_counts_and_hides_expired_values(self):
        self.render_headline({}, checks=r"""
state.live.simulation.response_supply = {
  state:'fresh', observed_at:new Date().toISOString(), fresh_max_age_seconds:360,
  condition_count:48, case_count:126, counts:{
    missing_material:0, awaiting_prerequisites:113, ready:0, enqueued:7, zero_reuse:10
  }, prerequisites:{p0:109, transport:0, threshold:4}
};
render();
const overview = document.getElementById('overview');
assert.match(overview.innerHTML, /48 组条件 · 126 例响应/);
assert.match(overview.innerHTML, /缺材料 <b>0<\/b>/);
assert.match(overview.innerHTML, /待前置验收 <b>113<\/b>/);
assert.match(overview.innerHTML, /已就绪 <b>0<\/b>/);
assert.match(overview.innerHTML, /已入队 <b>7<\/b>/);
assert.match(overview.innerHTML, /已核对零沉积复用 <b>10<\/b>/);
assert.match(overview.textContent, /双态零源资格 109 · 阈值前置证据 4/);
assert.match(overview.textContent, /原运行记录/);
state.live.simulation.response_supply.observed_at = '2020-01-01T00:00:00Z';
render();
assert.match(overview.textContent, /供料登记待更新/);
assert.doesNotMatch(overview.textContent, /缺材料/);
""")

    def test_r06_headline_uses_complete_plan_instead_of_legacy_core(self):
        result = self.render_headline({
            "revision": "r0.6", "totals": {"planned": 396, "solved": 0, "accepted": 0},
            "counts": {"core": {"planned": 384, "accepted": 384}},
        })
        self.assertIn("0 / 0 / 396", result["card"])
        self.assertIn("正式进度", result["card"])
        self.assertNotIn("384", result["card"])
        self.assertNotIn("核心科学验收", result["html"])
        self.assertIn('维护暂停', result["html"])

    def test_r06_headline_percentage_uses_396_and_does_not_use_engineering_completion(self):
        result = self.render_headline({"revision": "r0.6", "totals": {
            "planned": 396, "solver_finished": 4, "archived": 113, "solved": 105, "accepted": 99,
        }}, language="en")
        self.assertIn("4 / 113 / 99 / 396", result["card"])
        self.assertIn("Awaiting collection / Archive verified / Science accepted / Planned", result["card"])
        self.assertNotIn("25.0%", result["card"])

    def test_r05_headline_remains_compatible_and_maintenance_is_generic_in_english(self):
        result = self.render_headline({
            "revision": "r0.5", "totals": {"planned": 384, "solved": 96, "accepted": 96},
            "counts": {"core": {"planned": 384, "accepted": 96}},
        }, language="en")
        self.assertIn("96 / 96 / 384", result["card"])
        self.assertIn("Formal plan", result["card"])
        self.assertIn('Maintenance pause', result["html"])
        self.assertNotIn("Multicore test", result["html"])


if __name__ == "__main__":
    unittest.main()
